"""Master trade event detection.

Sources of truth, in priority order per snapshot cycle:
1. History deals (IN/OUT/INOUT/OUT_BY) with an overlapping time window -
   authoritative for opens, closes, partial closes, netting deposits and
   pending-order fills. Deduplicated by real deal tickets, so an open+close
   inside one poll interval is never missed and never duplicated.
2. Positions snapshot diff - catches SL/TP modifications and any position
   change that produced no deal.
3. Pending orders snapshot diff - place/modify/remove lifecycle.

Every event carries a unique event_key derived from REAL MT5 identifiers
(deal/order/position tickets), which the database enforces as unique per
master login -> idempotency.
"""
from __future__ import annotations

import logging

from app.core import constants as C
from app.core.utils import now_ms

log = logging.getLogger("engine.analyzer")

DEAL_PRUNE_MS = 24 * 3600 * 1000  # keep seen-deals memory for 24h


class MasterAnalyzer:
    def __init__(self, master_login: int):
        self.login = master_login
        self.positions: dict[int, dict] = {}
        self.orders: dict[int, dict] = {}
        self.seen_deals: dict[int, int] = {}  # deal ticket -> seen ts_ms
        self._baselined = False

    # ------------------------------------------------------------------

    def analyze(self, snap: dict) -> list[dict]:
        """snap: AccountSnapshot dict from worker. Returns list of event dicts."""
        events: list[dict] = []
        cur_pos = {int(p["ticket"]): p for p in snap.get("positions", [])}
        cur_orders = {int(o["ticket"]): o for o in snap.get("orders", [])}
        deals = sorted(snap.get("deals", []),
                       key=lambda d: (d.get("time_msc", 0), d.get("ticket", 0)))

        # First snapshot = baseline: record current state WITHOUT events.
        # This implements the default "copy only trades opened after engine
        # start" policy (existing positions are never auto-copied; that
        # requires the explicit sync-existing option handled by controller).
        if not self._baselined:
            self._baselined = True
            for d in deals:
                if int(d.get("type", -1)) in (0, 1):
                    self.seen_deals[int(d.get("ticket", 0))] = now_ms()
            for pid, p in cur_pos.items():
                self.positions[pid] = self._pos_state(p)
            for oticket, o in cur_orders.items():
                if int(o.get("state", 0)) in C.ORDER_STATE_ACTIVE:
                    self.orders[oticket] = self._order_state(o)
            return []

        filled_order_tickets = set()
        open_position_ids_this_cycle = set()

        # ---------------- 1) deals ----------------
        for d in deals:
            dticket = int(d.get("ticket", 0))
            d_type = int(d.get("type", -1))
            if d_type not in (0, 1):  # only BUY/SELL deals
                continue
            if dticket in self.seen_deals:
                continue
            self.seen_deals[dticket] = now_ms()
            pid = int(d.get("position_id", 0))
            if pid == 0:
                continue
            entry = int(d.get("entry", 0))
            volume = float(d.get("volume", 0.0))

            if entry in (C.DEAL_ENTRY_IN, C.DEAL_ENTRY_INOUT):
                prev_vol = self.positions.get(pid, {}).get("volume", 0.0)
                p_now = cur_pos.get(pid) or {}
                sl_now = float(p_now.get("sl", 0.0) or 0.0)
                tp_now = float(p_now.get("tp", 0.0) or 0.0)
                if prev_vol > C.VOLUME_EPS and entry == C.DEAL_ENTRY_IN:
                    # netting: deposit into existing position
                    events.append(self._ev(
                        C.EventType.POSITION_VOLUME_INCREASE.value,
                        f"VIN:{pid}:{dticket}", snap,
                        symbol=d.get("symbol"), position_id=pid,
                        order_id=int(d.get("order", 0)), deal_id=dticket,
                        side="BUY" if d_type == 0 else "SELL",
                        volume=volume, volume_before=prev_vol,
                        price=float(d.get("price", 0.0)),
                    ))
                    self.positions[pid] = {
                        "volume": prev_vol + volume,
                        "symbol": d.get("symbol"),
                        "type": d_type,
                        "sl": sl_now, "tp": tp_now,
                        "price_open": float(p_now.get("price_open", 0.0)),
                    }
                elif entry == C.DEAL_ENTRY_INOUT:
                    # reversal: close old then open remainder
                    if prev_vol > C.VOLUME_EPS:
                        events.append(self._ev(
                            C.EventType.POSITION_CLOSE_FULL.value,
                            f"CLOSE:{pid}:{dticket}", snap,
                            symbol=d.get("symbol"), position_id=pid,
                            order_id=int(d.get("order", 0)), deal_id=dticket,
                            side="BUY" if d_type == 0 else "SELL",
                            volume=prev_vol, volume_before=prev_vol,
                            price=float(d.get("price", 0.0)),
                            profit=float(d.get("profit", 0.0)),
                        ))
                    new_vol = max(0.0, volume - prev_vol)
                    if new_vol > C.VOLUME_EPS:
                        events.append(self._ev(
                            C.EventType.POSITION_OPEN.value,
                            f"OPEN:{pid}:{dticket}", snap,
                            symbol=d.get("symbol"), position_id=pid,
                            order_id=int(d.get("order", 0)), deal_id=dticket,
                            side="BUY" if d_type == 0 else "SELL",
                            volume=new_vol, price=float(d.get("price", 0.0)),
                            sl=sl_now, tp=tp_now,
                        ))
                        open_position_ids_this_cycle.add(pid)
                    self.positions[pid] = {
                        "volume": new_vol, "symbol": d.get("symbol"),
                        "type": d_type, "sl": sl_now, "tp": tp_now,
                        "price_open": float(p_now.get("price_open", 0.0))}
                else:
                    events.append(self._ev(
                        C.EventType.POSITION_OPEN.value,
                        f"OPEN:{pid}:{dticket}", snap,
                        symbol=d.get("symbol"), position_id=pid,
                        order_id=int(d.get("order", 0)), deal_id=dticket,
                        side="BUY" if d_type == 0 else "SELL",
                        volume=volume, price=float(d.get("price", 0.0)),
                        sl=sl_now, tp=tp_now,
                    ))
                    open_position_ids_this_cycle.add(pid)
                    self.positions[pid] = {
                        "volume": volume, "symbol": d.get("symbol"),
                        "type": d_type, "sl": sl_now, "tp": tp_now,
                        "price_open": float(p_now.get("price_open", 0.0))}

            # any deal (IN or OUT) referencing an order ticket proves that
            # order reached the broker - its disappearance is a FILL, not a REMOVE
            filled_order_tickets.add(int(d.get("order", 0)))
            if entry in (C.DEAL_ENTRY_OUT, C.DEAL_ENTRY_INOUT, C.DEAL_ENTRY_OUT_BY):
                prev = self.positions.get(pid)
                prev_vol = prev["volume"] if prev else 0.0
                remaining = float(cur_pos[pid]["volume"]) if pid in cur_pos else 0.0
                if remaining <= C.VOLUME_EPS:
                    events.append(self._ev(
                        C.EventType.POSITION_CLOSE_FULL.value,
                        f"CLOSE:{pid}:{dticket}", snap,
                        symbol=d.get("symbol"), position_id=pid,
                        order_id=int(d.get("order", 0)), deal_id=dticket,
                        side="BUY" if d_type == 0 else "SELL",
                        volume=prev_vol or volume,
                        volume_before=prev_vol or volume,
                        price=float(d.get("price", 0.0)),
                        profit=float(d.get("profit", 0.0)),
                    ))
                    self.positions.pop(pid, None)
                else:
                    events.append(self._ev(
                        C.EventType.POSITION_CLOSE_PARTIAL.value,
                        f"PART:{pid}:{dticket}", snap,
                        symbol=d.get("symbol"), position_id=pid,
                        order_id=int(d.get("order", 0)), deal_id=dticket,
                        side="BUY" if d_type == 0 else "SELL",
                        volume=volume, volume_before=prev_vol or (remaining + volume),
                        price=float(d.get("price", 0.0)),
                        profit=float(d.get("profit", 0.0)),
                    ))
                    if prev:
                        prev["volume"] = remaining
                # OUT deal closes the attached pending order, if any
                for oticket, od in list(self.orders.items()):
                    if int(od.get("position_id", 0)) == pid:
                        self.orders.pop(oticket, None)

        # ---------------- 2) positions diff ----------------
        for pid, p in cur_pos.items():
            known = self.positions.get(pid)
            if known is None:
                if pid not in open_position_ids_this_cycle:
                    # opened & deal not captured (fallback path)
                    events.append(self._ev(
                        C.EventType.POSITION_OPEN.value,
                        f"OPEN:{pid}:snap", snap,
                        symbol=p.get("symbol"), position_id=pid,
                        side="BUY" if int(p.get("type", 0)) == 0 else "SELL",
                        volume=float(p.get("volume", 0.0)),
                        price=float(p.get("price_open", 0.0)),
                        sl=float(p.get("sl", 0.0)), tp=float(p.get("tp", 0.0)),
                    ))
                self.positions[pid] = self._pos_state(p)
                continue
            # SL/TP modification
            sl, tp = float(p.get("sl", 0.0) or 0.0), float(p.get("tp", 0.0) or 0.0)
            if abs(sl - known["sl"]) > C.PRICE_EPS or abs(tp - known["tp"]) > C.PRICE_EPS:
                events.append(self._ev(
                    C.EventType.POSITION_MODIFY_SLTP.value,
                    f"MOD:{pid}:{sl}:{tp}", snap,
                    symbol=p.get("symbol"), position_id=pid,
                    side="BUY" if int(p.get("type", 0)) == 0 else "SELL",
                    volume=float(p.get("volume", 0.0)),
                    price=float(p.get("price_open", 0.0)),
                    sl=sl, tp=tp,
                ))
            # volume increased without seen deal (netting fallback)
            if float(p.get("volume", 0.0)) - known["volume"] > C.VOLUME_EPS:
                events.append(self._ev(
                    C.EventType.POSITION_VOLUME_INCREASE.value,
                    f"VIN:{pid}:snap:{round(float(p['volume']), 8)}", snap,
                    symbol=p.get("symbol"), position_id=pid,
                    side="BUY" if int(p.get("type", 0)) == 0 else "SELL",
                    volume=float(p.get("volume", 0.0)) - known["volume"],
                    volume_before=known["volume"],
                    price=float(p.get("price_open", 0.0)),
                ))
            self.positions[pid] = self._pos_state(p)

        for pid in list(self.positions.keys()):
            if pid not in cur_pos:
                known = self.positions.pop(pid)
                # vanished without an OUT deal seen this cycle: emit close so
                # slaves are closed too (safety-first). The deal may arrive in
                # the next snapshot with the overlapping window; event_key
                # dedup (CLOSE:pid:deal) would differ, but DB unique check on
                # mapping status prevents double-closing already-closed maps.
                events.append(self._ev(
                    C.EventType.POSITION_CLOSE_FULL.value,
                    f"CLOSE:{pid}:snap", snap,
                    symbol=known.get("symbol"), position_id=pid,
                    side="BUY" if known.get("type", 0) == 0 else "SELL",
                    volume=known.get("volume", 0.0),
                    volume_before=known.get("volume", 0.0),
                ))

        # ---------------- 3) pending orders diff ----------------
        for oticket, o in cur_orders.items():
            state = int(o.get("state", 0))
            if state not in C.ORDER_STATE_ACTIVE:
                continue
            known = self.orders.get(oticket)
            if known is None:
                events.append(self._ev(
                    C.EventType.ORDER_PLACE.value,
                    f"OP:{oticket}", snap,
                    symbol=o.get("symbol"), order_id=oticket,
                    position_id=int(o.get("position_id", 0) or 0),
                    side="BUY" if int(o.get("type", 0)) in (0, 2, 4, 6) else "SELL",
                    volume=float(o.get("volume_current", o.get("volume_initial", 0.0))),
                    price=float(o.get("price_open", 0.0)),
                    sl=float(o.get("sl", 0.0) or 0.0),
                    tp=float(o.get("tp", 0.0) or 0.0),
                    payload={"order_type": int(o.get("type", 0)),
                             "order_state": state},
                ))
                self.orders[oticket] = self._order_state(o)
            else:
                changed = (
                    abs(float(o.get("price_open", 0.0)) - known["price_open"]) > C.PRICE_EPS
                    or abs(float(o.get("sl", 0.0) or 0.0) - known["sl"]) > C.PRICE_EPS
                    or abs(float(o.get("tp", 0.0) or 0.0) - known["tp"]) > C.PRICE_EPS
                    or abs(float(o.get("volume_current", 0.0)) - known["volume_current"]) > C.VOLUME_EPS
                )
                if changed:
                    events.append(self._ev(
                        C.EventType.ORDER_MODIFY.value,
                        f"OM:{oticket}:{o.get('price_open')}:{o.get('sl')}:{o.get('tp')}",
                        snap,
                        symbol=o.get("symbol"), order_id=oticket,
                        side="BUY" if int(o.get("type", 0)) in (0, 2, 4, 6) else "SELL",
                        volume=float(o.get("volume_current", 0.0)),
                        price=float(o.get("price_open", 0.0)),
                        sl=float(o.get("sl", 0.0) or 0.0),
                        tp=float(o.get("tp", 0.0) or 0.0),
                        payload={"order_type": int(o.get("type", 0))},
                    ))
                self.orders[oticket] = self._order_state(o)

        for oticket in list(self.orders.keys()):
            if oticket not in cur_orders:
                self.orders.pop(oticket)
                if oticket in filled_order_tickets:
                    # fill handled by deal IN; nothing else to do
                    continue
                events.append(self._ev(
                    C.EventType.ORDER_REMOVE.value,
                    f"OR:{oticket}", snap,
                    order_id=oticket,
                ))

        # prune seen deals memory
        if len(self.seen_deals) > 20000:
            cutoff = now_ms() - DEAL_PRUNE_MS
            self.seen_deals = {t: ts for t, ts in self.seen_deals.items()
                               if ts > cutoff}
        return events

    # ------------------------------------------------------------------

    @staticmethod
    def _pos_state(p: dict) -> dict:
        return {
            "volume": float(p.get("volume", 0.0)),
            "symbol": p.get("symbol"),
            "type": int(p.get("type", 0)),
            "sl": float(p.get("sl", 0.0) or 0.0),
            "tp": float(p.get("tp", 0.0) or 0.0),
            "price_open": float(p.get("price_open", 0.0)),
        }

    @staticmethod
    def _order_state(o: dict) -> dict:
        return {
            "price_open": float(o.get("price_open", 0.0)),
            "sl": float(o.get("sl", 0.0) or 0.0),
            "tp": float(o.get("tp", 0.0) or 0.0),
            "volume_current": float(o.get("volume_current", 0.0)),
            "position_id": int(o.get("position_id", 0) or 0),
            "type": int(o.get("type", 0)),
        }

    @staticmethod
    def _ev(event_type: str, event_key: str, snap: dict, **fields) -> dict:
        ev = {
            "type": event_type,
            "event_key": event_key,
            "master_login": snap.get("login", 0),
            "detected_at_ms": now_ms(),
            "payload": fields.pop("payload", {}),
        }
        ev.update(fields)
        return ev
