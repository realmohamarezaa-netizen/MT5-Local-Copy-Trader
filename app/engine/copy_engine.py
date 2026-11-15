"""Copy engine: builds per-slave plans from master events and dispatches
parallel, independent actions to slave workers.

Guarantees:
- every event processed exactly once (DB unique event_key)
- no order sent twice for the same event (action row UNIQUE(event, terminal),
  state machine QUEUED->SENT->(FILLED|FAILED|RECONCILIATION_REQUIRED))
- unknown outcome (timeout / worker died mid-flight) never retried blindly:
  state becomes RECONCILIATION_REQUIRED and reconciler verifies with the
  broker account state before anything else happens.
"""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.engine.symbol_mapper import SymbolMapper
from typing import Optional

from app.core import constants as C
from app.core.utils import now_ms
from app.engine.volume_engine import compute_open_volume, compute_partial_close_volume

log = logging.getLogger("engine.copy")


class CopyEngine:
    def __init__(self, repo, mapper: "SymbolMapper"):
        self.repo = repo
        self.mapper = mapper

    # ------------------------------------------------------------------
    # dispatch
    # ------------------------------------------------------------------

    def plan_and_dispatch(
        self, event: dict, master_snapshot: Optional[dict],
        slave_runtimes: list, send_fn, engine_state: str,
        master_balance: float = 0.0, master_equity: float = 0.0,
    ) -> str:
        """Create event row + per-slave action rows, dispatch to workers.

        slave_runtimes: list of dicts {terminal_id, settings, snapshot,
        snapshot_age_ms, symbols, specs_cache, open_positions_count,
        open_total_volume, deviation_points}
        send_fn(terminal_id, action_id, action_type, params) -> bool
        Returns final event state string.
        """
        ev_type = event["type"]
        event_id = uuid.uuid4().hex
        event["id"] = event_id
        if not self.repo.insert_event(event):
            log.debug("duplicate event suppressed: %s", event["event_key"])
            return C.EventState.VERIFIED.value  # already handled

        # PAUSE policy: block new exposure, keep managing existing positions
        if engine_state == C.EngineState.PAUSED.value and \
                ev_type in C.OPENING_TYPES:
            self.repo.set_event_state(event_id, C.EventState.PAUSED_SKIPPED.value)
            return C.EventState.PAUSED_SKIPPED.value
        if engine_state in (C.EngineState.STOPPED.value,
                            C.EngineState.EMERGENCY.value):
            self.repo.set_event_state(event_id, C.EventState.BLOCKED.value)
            return C.EventState.BLOCKED.value

        dispatched = 0
        for rt in slave_runtimes:
            self._plan_single(event, rt, master_snapshot, send_fn,
                              master_balance, master_equity)

        # count dispatched actions
        actions = self.repo.list_actions_for_event(event_id)
        dispatched = sum(1 for a in actions if a["state"] != C.ActionState.FAILED.value)
        final = C.EventState.QUEUED.value if dispatched > 0 else C.EventState.VERIFIED.value
        if dispatched == 0 and ev_type in C.OPENING_TYPES:
            final = C.EventState.VERIFIED.value  # nothing to do (no slaves)
        self.repo.set_event_state(event_id, final)
        return final

    def _plan_single(self, event: dict, rt: dict, master_snapshot: Optional[dict],
                     send_fn, master_balance: float, master_equity: float) -> None:
        event_id = event["id"]
        ev_type = event["type"]
        settings = rt["settings"]
        terminal_id = rt["terminal_id"]

        # master position mapping row (for management events)
        mapping = None
        if event.get("position_id"):
            mapping = self.repo.get_mapping(event["position_id"], terminal_id)

        try:
            if ev_type == C.EventType.POSITION_OPEN.value:
                self._plan_open(event, rt, settings, master_snapshot, send_fn,
                                master_balance, master_equity)
            elif ev_type == C.EventType.POSITION_VOLUME_INCREASE.value:
                self._plan_volume_increase(event, rt, settings, send_fn,
                                           master_balance, master_equity)
            elif ev_type == C.EventType.POSITION_CLOSE_FULL.value:
                self._plan_close_full(event, mapping, rt, send_fn)
            elif ev_type == C.EventType.POSITION_CLOSE_PARTIAL.value:
                self._plan_close_partial(event, mapping, rt, settings, send_fn)
            elif ev_type == C.EventType.POSITION_MODIFY_SLTP.value:
                self._plan_modify_sltp(event, mapping, rt, settings, send_fn)
            elif ev_type == C.EventType.ORDER_PLACE.value:
                if settings.get("copy_pending"):
                    self._plan_place_pending(event, rt, settings, send_fn,
                                             master_balance, master_equity)
            elif ev_type == C.EventType.ORDER_MODIFY.value:
                self._plan_modify_pending(event, mapping, rt, settings, send_fn)
            elif ev_type == C.EventType.ORDER_REMOVE.value:
                self._plan_remove_pending(event, mapping, rt, send_fn)
            else:
                log.warning("unhandled event type %s", ev_type)
        except Exception as exc:
            log.exception("plan failed for terminal %s", terminal_id)
            self._record_block(event_id, terminal_id, str(exc))

    def _record_block(self, event_id: str, terminal_id: str, reason: str) -> None:
        action_id = uuid.uuid4().hex
        self.repo.insert_action(action_id, event_id, terminal_id,
                                {"blocked": reason})
        self.repo.update_action(action_id, state=C.ActionState.FAILED.value,
                                completed_at_ms=now_ms(),
                                error_message=reason)

    def _require_mapping(self, event: dict, mapping, event_id: str,
                         terminal_id: str, what: str) -> bool:
        if mapping is None or not mapping["slave_position_id"]:
            self._record_block(event_id, terminal_id,
                               f"{what}: no copied position mapping")
            return False
        if mapping["status"] not in ("OPEN", "PARTIAL"):
            self._record_block(event_id, terminal_id,
                               f"{what}: mapping status {mapping['status']}")
            return False
        return True

    # ---------------- plan builders ----------------

    def _plan_open(self, event, rt, settings, master_snapshot, send_fn,
                   master_balance, master_equity) -> None:
        event_id = event["id"]
        terminal_id = rt["terminal_id"]
        master_symbol = event.get("symbol") or ""

        slave_symbol, status = self.mapper.resolve(
            terminal_id, master_symbol, rt["symbols"])
        if slave_symbol is None:
            self._record_block(event_id, terminal_id,
                               f"symbol {master_symbol} unmapped "
                               f"(status={status}); map it manually")
            return

        specs = rt["specs_cache"].get(slave_symbol)
        if specs is None:
            self._record_block(event_id, terminal_id,
                               f"specs pending for {slave_symbol} "
                               "(will be cached automatically)")
            rt.setdefault("request_specs", []).append(slave_symbol)
            return

        account = rt["snapshot"] or {}
        volume = compute_open_volume(
            lot_mode=settings["lot_mode"],
            master_volume=float(event.get("volume") or 0.0),
            slave_account=account,
            specs=specs,
            lot_multiplier=settings["lot_multiplier"],
            fixed_lot=settings["fixed_lot"],
            balance_ratio=settings["balance_ratio"],
            equity_ratio=settings["equity_ratio"],
            max_lot=settings.get("max_lot"),
            master_balance=master_balance,
            master_equity=master_equity,
        )
        if not volume.ok:
            self._record_block(event_id, terminal_id, f"volume: {volume.reason}")
            return

        # risk gate
        from app.engine.risk_engine import check_slave
        decision = check_slave(settings, rt["snapshot"], rt["snapshot_age_ms"],
                               event, specs, rt["open_positions_count"],
                               rt["open_total_volume"])
        if not decision.ok:
            self._record_block(event_id, terminal_id, f"risk: {decision.reason}")
            return

        sl, tp = 0.0, 0.0
        sl_distance, tp_distance = 0.0, 0.0
        sltp_mode = settings.get("sltp_mode") or C.SlTpMode.ABSOLUTE.value
        master_price = float(event.get("price") or 0.0)
        master_sl = float(event.get("sl") or 0.0)
        master_tp = float(event.get("tp") or 0.0)
        if settings.get("copy_sl") and master_sl:
            if sltp_mode == C.SlTpMode.DISTANCE.value or master_price <= 0:
                sl_distance = abs(master_price - master_sl) if master_price > 0 else 0.0
            else:
                sl = master_sl
        if settings.get("copy_tp") and master_tp:
            if sltp_mode == C.SlTpMode.DISTANCE.value or master_price <= 0:
                tp_distance = abs(master_tp - master_price) if master_price > 0 else 0.0
            else:
                tp = master_tp
        if not settings.get("copy_sl"):
            sl = 0.0
            sl_distance = 0.0
        if not settings.get("copy_tp"):
            tp = 0.0
            tp_distance = 0.0

        params = {
            "symbol": slave_symbol,
            "side": event.get("side") or "BUY",
            "volume": volume.volume,
            "sl": sl,
            "tp": tp,
            "sltp_mode": C.SlTpMode.DISTANCE.value if (sl_distance or tp_distance)
            else C.SlTpMode.ABSOLUTE.value,
            "sl_distance": sl_distance,
            "tp_distance": tp_distance,
            "deviation_points": settings.get("max_slippage_points", 50),
            "allow_stops_adjust": bool(settings.get("allow_stops_adjust")),
            "magic": C.MAGIC_BASE,
            "comment": f"{C.COMMENT_PREFIX}:{event.get('position_id', 0)}",
            "precheck_margin": True,
        }
        action_id = uuid.uuid4().hex
        self.repo.insert_action(action_id, event_id, terminal_id, params)
        if send_fn(terminal_id, action_id, "open_position", params):
            self.repo.update_action(action_id, state=C.ActionState.SENT.value,
                                    sent_at_ms=now_ms())
        else:
            self.repo.update_action(action_id,
                                    state=C.ActionState.RECONCILIATION_REQUIRED.value,
                                    completed_at_ms=now_ms(),
                                    error_message="worker pipe unavailable")

    def _plan_volume_increase(self, event, rt, settings, send_fn,
                              master_balance, master_equity) -> None:
        """Netting deposit: treat like opening extra volume - send market
        order in same direction, mapped to the master position."""
        event2 = dict(event)
        event2["type"] = C.EventType.POSITION_OPEN.value
        self._plan_open(event2, rt, settings, None, send_fn,
                        master_balance, master_equity)

    def _plan_close_full(self, event, mapping, rt, send_fn) -> None:
        event_id = event["id"]
        terminal_id = rt["terminal_id"]
        if not self._require_mapping(event, mapping, event_id, terminal_id,
                                     "close full"):
            return
        params = {"slave_position_id": mapping["slave_position_id"]}
        action_id = uuid.uuid4().hex
        self.repo.insert_action(action_id, event_id, terminal_id, params)
        if send_fn(terminal_id, action_id, "close_full", params):
            self.repo.update_action(action_id, state=C.ActionState.SENT.value,
                                    sent_at_ms=now_ms())
        else:
            self.repo.update_action(action_id,
                                    state=C.ActionState.RECONCILIATION_REQUIRED.value,
                                    completed_at_ms=now_ms(),
                                    error_message="worker pipe unavailable")

    def _plan_close_partial(self, event, mapping, rt, settings, send_fn) -> None:
        event_id = event["id"]
        terminal_id = rt["terminal_id"]
        if not settings.get("copy_partial_close"):
            self._record_block(event_id, terminal_id, "partial close disabled")
            return
        if not self._require_mapping(event, mapping, event_id, terminal_id,
                                     "partial close"):
            return
        master_before = float(event.get("volume_before") or 0.0)
        closed = float(event.get("volume") or 0.0)
        if master_before <= 0:
            self._record_block(event_id, terminal_id, "unknown master volume before")
            return
        frac = closed / master_before
        specs = rt["specs_cache"].get(mapping["slave_symbol"])
        if specs is None:
            self._record_block(event_id, terminal_id,
                               f"specs pending for {mapping['slave_symbol']}")
            rt.setdefault("request_specs", []).append(mapping["slave_symbol"])
            return
        result = compute_partial_close_volume(
            frac, float(mapping["slave_volume_current"] or 0.0), specs)
        if not result.ok:
            self._record_block(event_id, terminal_id, f"partial close: {result.reason}")
            return
        params = {"slave_position_id": mapping["slave_position_id"],
                  "volume": result.volume}
        action_id = uuid.uuid4().hex
        self.repo.insert_action(action_id, event_id, terminal_id, params)
        if send_fn(terminal_id, action_id, "close_partial", params):
            self.repo.update_action(action_id, state=C.ActionState.SENT.value,
                                    sent_at_ms=now_ms())
        else:
            self.repo.update_action(action_id,
                                    state=C.ActionState.RECONCILIATION_REQUIRED.value,
                                    completed_at_ms=now_ms(),
                                    error_message="worker pipe unavailable")

    def _plan_modify_sltp(self, event, mapping, rt, settings, send_fn) -> None:
        event_id = event["id"]
        terminal_id = rt["terminal_id"]
        if not self._require_mapping(event, mapping, event_id, terminal_id,
                                     "modify SL/TP"):
            return
        master_price = float(event.get("price") or mapping["open_price_master"] or 0.0)
        master_sl = float(event.get("sl") or 0.0)
        master_tp = float(event.get("tp") or 0.0)
        slave_entry = mapping["open_price_slave"] or 0.0
        side = (event.get("side") or "BUY").upper()

        sl, tp = 0.0, 0.0
        if settings.get("copy_sl"):
            if settings.get("sltp_mode") == C.SlTpMode.DISTANCE.value and master_price > 0:
                dist = master_price - master_sl
                dist = dist if side == "BUY" else master_sl - master_price
                dist = abs(dist)
                sl = slave_entry - dist if side == "BUY" else slave_entry + dist
            else:
                sl = master_sl
        if settings.get("copy_tp"):
            if settings.get("sltp_mode") == C.SlTpMode.DISTANCE.value and master_price > 0:
                dist = master_tp - master_price
                dist = dist if side == "BUY" else master_price - master_tp
                dist = abs(dist)
                tp = slave_entry + dist if side == "BUY" else slave_entry - dist
            else:
                tp = master_tp

        params = {
            "slave_position_id": mapping["slave_position_id"],
            "sl": sl,
            "tp": tp,
            "digits": 5,
        }
        action_id = uuid.uuid4().hex
        self.repo.insert_action(action_id, event_id, terminal_id, params)
        if send_fn(terminal_id, action_id, "modify_sltp", params):
            self.repo.update_action(action_id, state=C.ActionState.SENT.value,
                                    sent_at_ms=now_ms())
        else:
            self.repo.update_action(action_id,
                                    state=C.ActionState.RECONCILIATION_REQUIRED.value,
                                    completed_at_ms=now_ms(),
                                    error_message="worker pipe unavailable")

    def _plan_place_pending(self, event, rt, settings, send_fn,
                            master_balance, master_equity) -> None:
        event_id = event["id"]
        terminal_id = rt["terminal_id"]
        master_symbol = event.get("symbol") or ""
        slave_symbol, status = self.mapper.resolve(terminal_id, master_symbol,
                                                   rt["symbols"])
        if slave_symbol is None:
            self._record_block(event_id, terminal_id,
                               f"symbol {master_symbol} unmapped for pending")
            return
        specs = rt["specs_cache"].get(slave_symbol)
        if specs is None:
            self._record_block(event_id, terminal_id,
                               f"specs pending for {slave_symbol}")
            rt.setdefault("request_specs", []).append(slave_symbol)
            return
        volume = compute_open_volume(
            lot_mode=settings["lot_mode"],
            master_volume=float(event.get("volume") or 0.0),
            slave_account=rt["snapshot"] or {},
            specs=specs,
            lot_multiplier=settings["lot_multiplier"],
            fixed_lot=settings["fixed_lot"],
            balance_ratio=settings["balance_ratio"],
            equity_ratio=settings["equity_ratio"],
            max_lot=settings.get("max_lot"),
            master_balance=master_balance,
            master_equity=master_equity,
        )
        if not volume.ok:
            self._record_block(event_id, terminal_id, f"volume: {volume.reason}")
            return

        order_type = int((event.get("payload") or {}).get("order_type", 0))
        master_price = float(event.get("price") or 0.0)
        if settings.get("pending_price_mode") == C.PendingPriceMode.DISTANCE.value and \
                rt["snapshot"]:
            # keep distance from master's own current tick: approximate with
            # master position snapshot equity? Fallback: absolute price.
            price = master_price
        else:
            price = master_price

        params = {
            "symbol": slave_symbol,
            "order_type": order_type,
            "volume": volume.volume,
            "price": price,
            "sl": float(event.get("sl") or 0.0) if settings.get("copy_sl") else 0.0,
            "tp": float(event.get("tp") or 0.0) if settings.get("copy_tp") else 0.0,
            "magic": C.MAGIC_BASE,
            "comment": f"{C.COMMENT_PREFIX}:ord:{event.get('order_id', 0)}",
        }
        action_id = uuid.uuid4().hex
        self.repo.insert_action(action_id, event_id, terminal_id, params)
        if send_fn(terminal_id, action_id, "place_pending", params):
            self.repo.update_action(action_id, state=C.ActionState.SENT.value,
                                    sent_at_ms=now_ms())
        else:
            self.repo.update_action(action_id,
                                    state=C.ActionState.RECONCILIATION_REQUIRED.value,
                                    completed_at_ms=now_ms(),
                                    error_message="worker pipe unavailable")

    def _plan_modify_pending(self, event, mapping, rt, settings, send_fn) -> None:
        event_id = event["id"]
        terminal_id = rt["terminal_id"]
        if mapping is None or not mapping["slave_order_id"]:
            self._record_block(event_id, terminal_id, "modify pending: no mapping")
            return
        params = {
            "slave_order_id": mapping["slave_order_id"],
            "price": float(event.get("price") or 0.0),
            "sl": float(event.get("sl") or 0.0) if settings.get("copy_sl") else 0.0,
            "tp": float(event.get("tp") or 0.0) if settings.get("copy_tp") else 0.0,
        }
        action_id = uuid.uuid4().hex
        self.repo.insert_action(action_id, event_id, terminal_id, params)
        if send_fn(terminal_id, action_id, "modify_pending", params):
            self.repo.update_action(action_id, state=C.ActionState.SENT.value,
                                    sent_at_ms=now_ms())
        else:
            self.repo.update_action(action_id,
                                    state=C.ActionState.RECONCILIATION_REQUIRED.value,
                                    completed_at_ms=now_ms(),
                                    error_message="worker pipe unavailable")

    def _plan_remove_pending(self, event, mapping, rt, send_fn) -> None:
        event_id = event["id"]
        terminal_id = rt["terminal_id"]
        if mapping is None or not mapping["slave_order_id"]:
            self._record_block(event_id, terminal_id, "remove pending: no mapping")
            return
        params = {"slave_order_id": mapping["slave_order_id"]}
        action_id = uuid.uuid4().hex
        self.repo.insert_action(action_id, event_id, terminal_id, params)
        if send_fn(terminal_id, action_id, "remove_pending", params):
            self.repo.update_action(action_id, state=C.ActionState.SENT.value,
                                    sent_at_ms=now_ms())
        else:
            self.repo.update_action(action_id,
                                    state=C.ActionState.RECONCILIATION_REQUIRED.value,
                                    completed_at_ms=now_ms(),
                                    error_message="worker pipe unavailable")

    # ------------------------------------------------------------------
    # results
    # ------------------------------------------------------------------

    def on_action_result(self, action_id: str, ok: bool, data: dict,
                         error: str, error_code: int, retcode: int,
                         latencies: dict, result_latency_us: int) -> Optional[str]:
        action = self.repo.get_action(action_id)
        if action is None:
            log.warning("result for unknown action %s", action_id)
            return None
        if action["state"] in (C.ActionState.VERIFIED.value, C.ActionState.FAILED.value):
            return action["state"]  # already finalized (duplicate delivery)

        event_id = action["event_id"]
        terminal_id = action["terminal_id"]
        params = action["params"] or {}
        event = self.repo.db.query_one("SELECT * FROM events WHERE id=?", (event_id,))

        if not ok:
            state = (C.ActionState.RECONCILIATION_REQUIRED.value
                     if retcode in C.RETRYABLE_RETCODES or error_code == -1
                     else C.ActionState.FAILED.value)
            self.repo.update_action(
                action_id, state=state, completed_at_ms=now_ms(),
                error_message=error, error_code=error_code,
                latency_total_us=result_latency_us)
            self.repo.set_event_state(event_id, state)
            return state

        # success paths by action type
        import json as _json
        try:
            params = _json.loads(action["params"]) if action["params"] else {}
        except (TypeError, ValueError):
            params = {}
        action_type = (params.get("_type") or
                       self._infer_action_type(action, event))
        if action_type == "open_position":
            master_pos = (event["master_position_id"] if event else None) or \
                self._master_pos_from_params(params)
            mapping = self.repo.get_mapping(master_pos, terminal_id) \
                if master_pos else None
            m_price = float(event["price"]) if event and event["price"] else 0.0
            s_price = float(data.get("price") or 0.0)
            deviation = (abs(s_price - m_price) / m_price * 100.0
                         if m_price > 0 and s_price > 0 else None)
            if mapping is None:
                self.repo.insert_mapping(
                    master_login=event["master_login"] if event else 0,
                    master_position_id=master_pos or 0,
                    master_order_id=event["master_order_id"] if event else None,
                    master_deal_id=event["master_deal_id"] if event else None,
                    master_symbol=event["master_symbol"] if event else
                    params.get("master_symbol", ""),
                    master_volume_initial=event["volume"] if event else None,
                    master_volume_current=event["volume"] if event else None,
                    slave_terminal_id=terminal_id,
                    slave_symbol=params.get("symbol"),
                    slave_position_id=int(data.get("position_id", 0)),
                    slave_order_id=int(data.get("order", 0)),
                    slave_volume_initial=data.get("volume") or params.get("volume"),
                    slave_volume_current=data.get("volume") or params.get("volume"),
                    status=C.MappingStatus.OPEN.value,
                    open_price_master=event["price"] if event else None,
                    open_price_slave=data.get("price"),
                    deviation_percent=deviation,
                    created_at_ms=now_ms(),
                )
            else:
                self.repo.update_mapping(
                    mapping["id"],
                    slave_position_id=int(data.get("position_id", 0)),
                    slave_order_id=int(data.get("order", 0)),
                    status=C.MappingStatus.OPEN.value,
                )
            final_state = C.ActionState.VERIFIED.value
        elif action_type == "close_full":
            master_pos = event["master_position_id"] if event else None
            mapping = self.repo.get_mapping(master_pos, terminal_id) if master_pos else None
            if mapping:
                self.repo.update_mapping(mapping["id"],
                                         status=C.MappingStatus.CLOSED.value,
                                         slave_volume_current=0.0)
            final_state = C.ActionState.VERIFIED.value
        elif action_type == "close_partial":
            master_pos = event["master_position_id"] if event else None
            mapping = self.repo.get_mapping(master_pos, terminal_id) if master_pos else None
            if mapping:
                closed = float(data.get("closed_volume") or 0.0)
                new_vol = max(0.0, float(mapping["slave_volume_current"] or 0.0) - closed)
                self.repo.update_mapping(
                    mapping["id"],
                    slave_volume_current=new_vol,
                    status=(C.MappingStatus.CLOSED.value
                            if new_vol <= C.VOLUME_EPS
                            else C.MappingStatus.PARTIAL.value))
            final_state = C.ActionState.VERIFIED.value
        elif action_type == "place_pending":
            master_pos = event["master_position_id"] if event else None
            mapping = self.repo.get_mapping(master_pos, terminal_id) if master_pos else None
            if mapping is None:
                self.repo.insert_mapping(
                    master_login=event["master_login"] if event else 0,
                    master_position_id=master_pos or 0,
                    master_order_id=event["master_order_id"] if event else None,
                    master_symbol=event["master_symbol"] if event else "",
                    slave_terminal_id=terminal_id,
                    slave_symbol=params.get("symbol"),
                    slave_order_id=int(data.get("order", 0)),
                    status=C.MappingStatus.PENDING_ORDER.value,
                    created_at_ms=now_ms(),
                )
            final_state = C.ActionState.FILLED.value
        elif action_type == "modify_sltp":
            final_state = C.ActionState.VERIFIED.value
        elif action_type in ("modify_pending", "remove_pending"):
            if mapping := self._mapping_for_event(event, terminal_id):
                if action_type == "remove_pending":
                    self.repo.update_mapping(mapping["id"],
                                             status=C.MappingStatus.CLOSED.value)
            final_state = C.ActionState.VERIFIED.value
        else:
            final_state = C.ActionState.VERIFIED.value

        self.repo.update_action(
            action_id, state=final_state, completed_at_ms=now_ms(),
            result={"data": data, "retcode": retcode, "latencies": latencies},
            latency_total_us=result_latency_us)
        self.repo.set_event_state(event_id, final_state)
        return final_state

    def _mapping_for_event(self, event, terminal_id):
        if event is None or not event["master_position_id"]:
            return None
        return self.repo.get_mapping(event["master_position_id"], terminal_id)

    @staticmethod
    def _infer_action_type(action_row, event) -> str:
        # event type determines the action type; params don't carry it
        if event is not None:
            return {
                C.EventType.POSITION_OPEN.value: "open_position",
                C.EventType.POSITION_VOLUME_INCREASE.value: "open_position",
                C.EventType.POSITION_CLOSE_FULL.value: "close_full",
                C.EventType.POSITION_CLOSE_PARTIAL.value: "close_partial",
                C.EventType.POSITION_MODIFY_SLTP.value: "modify_sltp",
                C.EventType.ORDER_PLACE.value: "place_pending",
                C.EventType.ORDER_MODIFY.value: "modify_pending",
                C.EventType.ORDER_REMOVE.value: "remove_pending",
            }.get(event["type"], "unknown")
        return "unknown"

    @staticmethod
    def _master_pos_from_params(params) -> int:
        comment = params.get("comment") or ""
        if comment.startswith(C.COMMENT_PREFIX + ":"):
            try:
                return int(comment.split(":", 1)[1])
            except (ValueError, IndexError):
                return 0
        return 0
