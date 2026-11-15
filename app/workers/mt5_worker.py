"""Dedicated MT5 worker per terminal.

Design rules enforced here:
- One MetaTrader5 Python connection per process (API limitation) -> one
  process per terminal gives fully independent sessions.
- All mt5.* calls serialized by a lock; action execution never blocks the
  controller and never blocks other workers.
- Fast polling for master (positions + incremental history deals with
  overlapping window), moderate polling for slaves (UI data).
- Order execution: symbol validation, filling-mode detection, margin
  pre-check (order_check), sane-stop validation, INVALID_STOPS single
  retry (only when allow_stops_adjust), post-fill verification.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

from app.core import constants as C
from app.core.utils import now_ms
from app.ipc import protocol as P
from app.ipc.transport import MessageConnection, connect_client

log = logging.getLogger("worker.mt5")

# values mirrored from MetaTrader5 docs (kept here to avoid importing the
# native module at import time on non-Windows dev machines)
TRADE_ACTION_DEAL = 1
TRADE_ACTION_PENDING = 5
TRADE_ACTION_SLTP = 6
TRADE_ACTION_MODIFY = 7
TRADE_ACTION_REMOVE = 8

ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_RETURN = 2

SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2

TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_DONE_PARTIAL = 10010
TRADE_RETCODE_PLACED = 10008
TRADE_RETCODE_NO_MONEY = 10019
TRADE_RETCODE_INVALID_STOPS = 10016
TRADE_RETCODE_MARKET_CLOSED = 10018
TRADE_RETCODE_TRADE_DISABLED = 10017

SLTP_SANITY_RATIO = 0.5  # reject stops more than 50% away from price


@dataclass
class WorkerConfig:
    terminal_id: str
    terminal_path: str
    login: Optional[int] = None
    password: Optional[str] = None
    server: Optional[str] = None
    is_master: bool = False
    poll_ms_master: int = 50
    poll_ms_slave: int = 250
    deal_window_sec: int = 600
    slippage_points: int = 50
    precheck_margin: bool = True

    @staticmethod
    def from_dict(d: dict) -> "WorkerConfig":
        return WorkerConfig(
            terminal_id=d["terminal_id"],
            terminal_path=d["terminal_path"],
            login=d.get("login"),
            password=d.get("password"),
            server=d.get("server"),
            is_master=bool(d.get("is_master", False)),
            poll_ms_master=int(d.get("poll_ms_master", 50)),
            poll_ms_slave=int(d.get("poll_ms_slave", 250)),
            deal_window_sec=int(d.get("deal_window_sec", 600)),
            slippage_points=int(d.get("slippage_points", 50)),
            precheck_margin=bool(d.get("precheck_margin", True)),
        )


def _nt_to_dict(nt) -> dict:
    """Convert a MetaTrader5 namedtuple to a plain dict (safe getattr)."""
    if nt is None:
        return {}
    try:
        return nt._asdict()
    except AttributeError:
        return dict(nt)


class Mt5Worker:
    def __init__(self, cfg: WorkerConfig, pipe_address: str):
        self.cfg = cfg
        self.address = pipe_address
        self.conn: Optional[MessageConnection] = None
        self.mt5 = None  # native module, imported lazily on Windows
        self.mt5_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.connected_terminal = False
        self.poll_rate = cfg.poll_ms_master if cfg.is_master else cfg.poll_ms_slave
        self.deal_window_sec = cfg.deal_window_sec
        self.slippage_points = cfg.slippage_points
        self.precheck_margin = cfg.precheck_margin
        self._reader_thread: Optional[threading.Thread] = None
        self._idle_cycles = 0

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def run(self) -> None:
        self.conn = connect_client(self.address)
        try:
            import MetaTrader5 as mt5  # official MetaTrader5 package (Windows)
            self.mt5 = mt5
        except Exception as exc:
            self.conn.send(P.hello(self.cfg.terminal_id, ok=False,
                                   error=f"MetaTrader5 module unavailable: {exc}"))
            return

        if not self._initialize_terminal():
            self.conn.send(P.hello(self.cfg.terminal_id, ok=False,
                                   error=self._last_error()))
            # keep trying to initialize in background loop
            self._reconnect_loop(initial_failed=True)
            return

        self._send_hello()
        self._reader_thread = threading.Thread(
            target=self._reader_loop, name="worker-reader", daemon=True)
        self._reader_thread.start()
        try:
            self._poll_loop()
        finally:
            with self.mt5_lock:
                try:
                    self.mt5.shutdown()
                except Exception:
                    pass

    def _initialize_terminal(self) -> bool:
        """Attach to the terminal. Uses the terminal's current logged-in
        session when login/password not provided."""
        mt5 = self.mt5
        with self.mt5_lock:
            kwargs = {"path": self.cfg.terminal_path}
            if self.cfg.login and self.cfg.password and self.cfg.server:
                kwargs.update(login=int(self.cfg.login),
                              password=self.cfg.password,
                              server=self.cfg.server)
            ok = mt5.initialize(**kwargs)
            if not ok:
                return False
            acc = mt5.account_info()
            self.connected_terminal = acc is not None
            return True

    def _last_error(self) -> str:
        try:
            return str(self.mt5.last_error())
        except Exception:
            return "unknown mt5 error"

    def _send_hello(self) -> None:
        mt5 = self.mt5
        with self.mt5_lock:
            acc = mt5.account_info()
            term = mt5.terminal_info()
            version = ".".join(str(v) for v in mt5.version())
            symbols = []
            if acc is not None:
                try:
                    all_symbols = mt5.symbols_get()
                    symbols = [s.name for s in (all_symbols or [])]
                except Exception:
                    symbols = []
            account = _nt_to_dict(acc)
            if term is not None:
                td = _nt_to_dict(term)
                account["terminal_trade_allowed"] = bool(td.get("trade_allowed", False))
                account["terminal_connected"] = bool(td.get("connected", False))
                account["data_path"] = td.get("data_path", "")
        self.conn.send(P.hello(
            self.cfg.terminal_id, ok=account.get("login") is not None
            and account.get("login", 0) != 0,
            account=account, symbols=symbols[:20000], mt5_version=version))

    def shutdown(self) -> None:
        self.stop_event.set()

    # ------------------------------------------------------------------
    # reader thread: controller -> worker actions
    # ------------------------------------------------------------------

    def _reader_loop(self) -> None:
        while not self.stop_event.is_set():
            msg = self.conn.recv(timeout=0.25)
            if msg is None:
                continue
            mtype = msg.get("type")
            if mtype == P.MSG_SHUTDOWN:
                self.stop_event.set()
                return
            if mtype == P.MSG_CONFIGURE:
                self.poll_rate = (msg.get("poll_ms_master") if self.cfg.is_master
                                  else msg.get("poll_ms_slave")) or self.poll_rate
                self.deal_window_sec = msg.get("deal_window_sec", self.deal_window_sec)
                continue
            if mtype == P.MSG_ACTION:
                threading.Thread(target=self._execute_action, args=(msg,),
                                 daemon=True).start()

    # ------------------------------------------------------------------
    # polling loop
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        mt5 = self.mt5
        while not self.stop_event.is_set():
            cycle_start = time.perf_counter()
            try:
                with self.mt5_lock:
                    acc = mt5.account_info()
                    if acc is None:
                        self._handle_connection_lost()
                        continue
                    positions = mt5.positions_get() or []
                    orders = mt5.orders_get() or []
                    deals = []
                    window_from = 0
                    if self.cfg.is_master:
                        to_time = time.time() + 60
                        from_time = to_time - self.deal_window_sec
                        import datetime as _dt
                        d_from = _dt.datetime.utcfromtimestamp(from_time)
                        d_to = _dt.datetime.utcfromtimestamp(to_time)
                        raw = mt5.history_deals_get(d_from, d_to)
                        deals = list(raw or [])
                        window_from = int(from_time * 1000)

                snap = self._build_snapshot(acc, positions, orders, deals, window_from)
                # adaptive slowdown for slaves: nothing changed for many cycles
                rate = self.poll_rate
                if not self.cfg.is_master:
                    if self._snapshot_signature(snap) != getattr(self, "_last_sig", None):
                        self._idle_cycles = 0
                        rate = self.poll_rate
                    else:
                        self._idle_cycles += 1
                        if self._idle_cycles > 40:       # ~10s idle at 250ms
                            rate = min(self.poll_rate * 3, 1000)
                    self._last_sig = self._snapshot_signature(snap)
                build_ms = (time.perf_counter() - cycle_start) * 1000.0
                self.conn.send(P.snapshot(
                    self.cfg.terminal_id, snap,
                    {"build_ms": round(build_ms, 1)}))
            except (OSError, EOFError):
                log.info("controller pipe closed for %s; exiting poll loop",
                         self.cfg.terminal_id)
                return
            except Exception:
                log.exception("poll cycle error for %s", self.cfg.terminal_id)
                self._handle_connection_lost()
                continue

            elapsed = time.perf_counter() - cycle_start
            sleep_s = max(0.003, rate / 1000.0 - elapsed)
            # wake up in small steps so actions grab the mt5 lock quickly
            end_t = time.perf_counter() + sleep_s
            while time.perf_counter() < end_t and not self.stop_event.is_set():
                time.sleep(min(0.005, max(0.0, end_t - time.perf_counter())))

    def _snapshot_signature(self, snap: dict) -> tuple:
        pos = tuple(
            (p["ticket"], round(p["volume"], 8), p["sl"], p["tp"],
             round(p["profit"], 2))
            for p in snap["positions"]
        )
        return (snap["equity"], snap["balance"], pos, len(snap["orders"]))

    def _build_snapshot(self, acc, positions, orders, deals, window_from: int) -> dict:
        term = None
        with self.mt5_lock:
            term = self.mt5.terminal_info()
        term_d = _nt_to_dict(term)
        acc_d = _nt_to_dict(acc)
        return {
            "terminal_id": self.cfg.terminal_id,
            "login": int(acc_d.get("login", 0) or 0),
            "account_name": acc_d.get("name", ""),
            "server": acc_d.get("server", ""),
            "currency": acc_d.get("currency", ""),
            "leverage": int(acc_d.get("leverage", 0) or 0),
            "margin_mode": int(acc_d.get("margin_mode", 0) or 0),
            "trade_allowed": bool(acc_d.get("trade_allowed", False)),
            "terminal_trade_allowed": bool(term_d.get("trade_allowed", False)),
            "connected_to_broker": bool(term_d.get("connected", False)),
            "balance": float(acc_d.get("balance", 0.0)),
            "equity": float(acc_d.get("equity", 0.0)),
            "margin": float(acc_d.get("margin", 0.0)),
            "margin_free": float(acc_d.get("margin_free", 0.0)),
            "margin_level": float(acc_d.get("margin_level", 0.0)),
            "profit": float(acc_d.get("profit", 0.0)),
            "positions": [_nt_to_dict(p) for p in positions],
            "orders": [_nt_to_dict(o) for o in orders],
            "deals": [_nt_to_dict(d) for d in deals] if self.cfg.is_master else [],
            "deal_window_from_ms": window_from,
            "ts_utc_ms": now_ms(),
            "ts_monotonic": time.perf_counter(),
        }

    def _handle_connection_lost(self) -> None:
        self.conn.send(P.status(self.cfg.terminal_id, "DISCONNECTED",
                                self._last_error()))
        self._reconnect_loop()

    def _reconnect_loop(self, initial_failed: bool = False) -> None:
        attempt = 0
        while not self.stop_event.is_set():
            attempt += 1
            time.sleep(min(10.0, 1.0 + attempt * 0.5))
            try:
                with self.mt5_lock:
                    if self.mt5.initialize(path=self.cfg.terminal_path):
                        acc = self.mt5.account_info()
                        if acc is not None:
                            self.connected_terminal = True
                            self.conn.send(P.status(self.cfg.terminal_id, "CONNECTED"))
                            self._send_hello()
                            if initial_failed:
                                self._reader_thread = threading.Thread(
                                    target=self._reader_loop, name="worker-reader",
                                    daemon=True)
                                self._reader_thread.start()
                            return
            except Exception:
                pass
            self.conn.send(P.status(self.cfg.terminal_id, "CONNECTING",
                                    f"retry {attempt}"))

    # ------------------------------------------------------------------
    # action execution
    # ------------------------------------------------------------------

    def _execute_action(self, msg: dict) -> None:
        action_id = msg["action_id"]
        action_type = msg["action_type"]
        params = msg.get("params", {})
        t0 = time.perf_counter()
        try:
            handler = getattr(self, f"_act_{action_type}", None)
            if handler is None:
                self.conn.send(P.action_result(
                    self.cfg.terminal_id, action_id, ok=False,
                    error=f"unknown action {action_type}"))
                return
            data = handler(params)
            latency_us = int((time.perf_counter() - t0) * 1_000_000)
            self.conn.send(P.action_result(
                self.cfg.terminal_id, action_id, ok=data.pop("ok", True),
                data=data, error=data.pop("error", ""),
                error_code=data.pop("error_code", 0),
                retcode=data.pop("retcode", 0),
                latencies={"worker_exec_us": latency_us}))
        except (OSError, EOFError):
            log.warning("pipe closed while answering action %s", action_id)
        except Exception as exc:
            log.exception("action %s failed", action_type)
            try:
                self.conn.send(P.action_result(
                    self.cfg.terminal_id, action_id, ok=False,
                    error=str(exc), error_code=-1))
            except Exception:
                pass

    # ---------------- helpers ----------------

    def _choose_filling(self, symbol_info) -> int:
        fm = int(getattr(symbol_info, "filling_mode", 0) or 0)
        if fm & SYMBOL_FILLING_IOC:
            return ORDER_FILLING_IOC
        if fm & SYMBOL_FILLING_FOK:
            return ORDER_FILLING_FOK
        return ORDER_FILLING_RETURN

    def _get_symbol(self, symbol: str):
        info = self.mt5.symbol_info(symbol)
        if info is None:
            # try to select the symbol in Market Watch first
            self.mt5.symbol_select(symbol, True)
            info = self.mt5.symbol_info(symbol)
        return info

    def _validate_stops(self, side_buy: bool, price: float, sl: float, tp: float) -> Optional[str]:
        """Reject absurd stops before hitting the broker."""
        if sl and price and abs(price - sl) / max(price, 1e-9) > SLTP_SANITY_RATIO:
            return "SL_UNREASONABLE_DISTANCE"
        if tp and price and abs(tp - price) / max(price, 1e-9) > SLTP_SANITY_RATIO:
            return "TP_UNREASONABLE_DISTANCE"
        return None

    def _result_common(self, res) -> dict:
        return {
            "retcode": int(getattr(res, "retcode", 0) or 0),
            "order": int(getattr(res, "order", 0) or 0),
            "deal": int(getattr(res, "deal", 0) or 0),
            "volume": float(getattr(res, "volume", 0.0) or 0.0),
            "price": float(getattr(res, "price", 0.0) or 0.0),
            "comment": str(getattr(res, "comment", "") or ""),
        }

    def _send_order(self, request: dict) -> tuple:
        res = self.mt5.order_send(request)
        return res, _nt_to_dict(res)

    # ---------------- action handlers ----------------

    def _act_open_position(self, p: dict) -> dict:
        with self.mt5_lock:
            mt5 = self.mt5
            symbol = p["symbol"]
            is_buy = str(p["side"]).upper() == "BUY"
            volume = float(p["volume"])
            info = self._get_symbol(symbol)
            if info is None:
                return {"ok": False, "error": f"symbol not found: {symbol}",
                        "error_code": -2}
            if info.trade_mode == 0:
                return {"ok": False, "error": "trading disabled for symbol",
                        "error_code": -3}
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return {"ok": False, "error": "no tick data", "error_code": -4}
            price = float(tick.ask) if is_buy else float(tick.bid)

            sl = p.get("sl") or 0.0
            tp = p.get("tp") or 0.0
            # DISTANCE mode: resolve absolute levels from own tick
            if p.get("sltp_mode") == "DISTANCE":
                sl_dist = float(p.get("sl_distance") or 0.0)
                tp_dist = float(p.get("tp_distance") or 0.0)
                if sl_dist > 0:
                    sl = price - sl_dist if is_buy else price + sl_dist
                if tp_dist > 0:
                    tp = price + tp_dist if is_buy else price - tp_dist
            insane = self._validate_stops(is_buy, price, sl, tp)
            if insane:
                return {"ok": False, "error": insane, "error_code": -5}
            digits = int(getattr(info, "digits", 5))
            sl = round(sl, digits) if sl else 0.0
            tp = round(tp, digits) if tp else 0.0

            request = {
                "action": TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": C.ORDER_TYPE_BUY if is_buy else C.ORDER_TYPE_SELL,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": int(p.get("deviation_points", self.slippage_points)),
                "magic": int(p.get("magic", C.MAGIC_BASE)),
                "comment": str(p.get("comment", ""))[:31],
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._choose_filling(info),
            }

            # margin pre-check (optional, adds one local roundtrip)
            if self.precheck_margin:
                check = mt5.order_check(request)
                if check is None or int(getattr(check, "retcode", 0)) not in (
                        0, TRADE_RETCODE_PLACED, TRADE_RETCODE_DONE,
                        TRADE_RETCODE_DONE_PARTIAL):
                    return {"ok": False, "error": "order_check rejected",
                            "error_code": int(getattr(check, "retcode", 0) or -6),
                            "retcode": int(getattr(check, "retcode", 0) or 0)}

            res, res_d = self._send_order(request)
            retcode = res_d.get("retcode", 0)

            # single controlled retry on INVALID_STOPS, only when allowed:
            if retcode == TRADE_RETCODE_INVALID_STOPS and sl == 0.0 and tp == 0.0:
                pass  # stops were already empty; nothing to relax
            elif retcode == TRADE_RETCODE_INVALID_STOPS and p.get("allow_stops_adjust"):
                stops_level = int(getattr(info, "trade_stops_level", 0)) * \
                    float(getattr(info, "point", 0.00001))
                if is_buy:
                    if sl and sl > price - stops_level:
                        sl = round(price - stops_level, digits)
                    if tp and tp < price + stops_level:
                        tp = round(price + stops_level, digits)
                else:
                    if sl and sl < price + stops_level:
                        sl = round(price + stops_level, digits)
                    if tp and tp > price - stops_level:
                        tp = round(price - stops_level, digits)
                request.update({"sl": sl, "tp": tp})
                res, res_d = self._send_order(request)
                retcode = res_d.get("retcode", 0)

            if retcode not in (TRADE_RETCODE_DONE, TRADE_RETCODE_DONE_PARTIAL,
                               TRADE_RETCODE_PLACED):
                # IMPORTANT: no blind resend on timeout-like codes
                return {"ok": False, "retcode": retcode,
                        "error_code": retcode,
                        "error": C.RETCODES.get(retcode, f"retcode {retcode}")}

            order_ticket = res_d.get("order", 0)
            position_id = self._verify_position_exists(symbol, order_ticket)
            if position_id is None:
                return {"ok": False, "retcode": retcode, "error_code": retcode,
                        "error": "FILL_UNVERIFIED",
                        **{k: res_d.get(k) for k in ("order", "volume", "price")}}
            out = self._result_common(type("R", (), res_d))
            out.update({
                "ok": True,
                "position_id": position_id,
                "symbol_info": {
                    "digits": digits,
                    "point": float(getattr(info, "point", 0.0)),
                    "volume_min": float(getattr(info, "volume_min", 0.0)),
                    "volume_max": float(getattr(info, "volume_max", 0.0)),
                    "volume_step": float(getattr(info, "volume_step", 0.0)),
                },
            })
            return out

    def _verify_position_exists(self, symbol: str, order_ticket: int) -> Optional[int]:
        """After DONE: confirm the position really exists before reporting
        success (Order Reconciliation / Slave Position Verification)."""
        if not order_ticket:
            return None
        poss = self.mt5.positions_get(symbol=symbol) or []
        for pos in poss:
            if int(getattr(pos, "ticket", 0)) == order_ticket:
                return order_ticket
            if int(getattr(pos, "identifier", 0)) == order_ticket:
                return int(pos.ticket)
        # hedging: position ticket == order ticket in most cases; fallback scan:
        for pos in poss:
            if pos.magic == C.MAGIC_BASE:
                return int(pos.ticket)
        return None

    def _act_modify_sltp(self, p: dict) -> dict:
        with self.mt5_lock:
            mt5 = self.mt5
            ticket = int(p["slave_position_id"])
            poss = mt5.positions_get(ticket=ticket) or []
            if not poss:
                return {"ok": False, "error": "position not found",
                        "error_code": -7}
            pos = poss[0]
            sl = float(p.get("sl") or 0.0)
            tp = float(p.get("tp") or 0.0)
            request = {
                "action": TRADE_ACTION_SLTP,
                "symbol": pos.symbol,
                "position": ticket,
                "sl": round(sl, int(p.get("digits", 5))),
                "tp": round(tp, int(p.get("digits", 5))),
            }
            res, res_d = self._send_order(request)
            retcode = res_d.get("retcode", 0)
            ok = retcode in (TRADE_RETCODE_DONE, TRADE_RETCODE_PLACED)
            return {"ok": ok, "retcode": retcode,
                    "error_code": retcode if not ok else 0,
                    "error": C.RETCODES.get(retcode) if not ok else ""}

    def _close_request(self, pos, volume: float) -> dict:
        mt5 = self.mt5
        is_buy = int(pos.type) == C.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(pos.symbol)
        price = float(tick.bid) if is_buy else float(tick.ask)
        info = self._get_symbol(pos.symbol)
        return {
            "action": TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": round(volume, 8),
            "type": C.ORDER_TYPE_SELL if is_buy else C.ORDER_TYPE_BUY,
            "position": int(pos.ticket),
            "price": price,
            "deviation": self.slippage_points,
            "magic": C.MAGIC_BASE,
            "comment": f"{C.COMMENT_PREFIX}:close"[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._choose_filling(info),
        }

    def _act_close_full(self, p: dict) -> dict:
        with self.mt5_lock:
            ticket = int(p["slave_position_id"])
            poss = self.mt5.positions_get(ticket=ticket) or []
            if not poss:
                return {"ok": False, "error": "position not found",
                        "error_code": -7}
            res, res_d = self._send_order(self._close_request(poss[0], poss[0].volume))
            retcode = res_d.get("retcode", 0)
            ok = retcode in (TRADE_RETCODE_DONE, TRADE_RETCODE_DONE_PARTIAL)
            still = self.mt5.positions_get(ticket=ticket)
            verified = still is None or len(still) == 0
            return {"ok": ok and verified, "retcode": retcode,
                    "error_code": retcode if not ok else 0,
                    "error": C.RETCODES.get(retcode) if not ok else "",
                    "closed_volume": res_d.get("volume", 0.0),
                    "verified": verified}

    def _act_close_partial(self, p: dict) -> dict:
        with self.mt5_lock:
            ticket = int(p["slave_position_id"])
            volume = float(p["volume"])
            poss = self.mt5.positions_get(ticket=ticket) or []
            if not poss:
                return {"ok": False, "error": "position not found",
                        "error_code": -7}
            pos = poss[0]
            if volume >= pos.volume - C.VOLUME_EPS:
                return self._act_close_full({"slave_position_id": ticket})
            res, res_d = self._send_order(self._close_request(pos, volume))
            retcode = res_d.get("retcode", 0)
            ok = retcode in (TRADE_RETCODE_DONE, TRADE_RETCODE_DONE_PARTIAL)
            return {"ok": ok, "retcode": retcode,
                    "error_code": retcode if not ok else 0,
                    "error": C.RETCODES.get(retcode) if not ok else "",
                    "closed_volume": res_d.get("volume", 0.0)}

    def _act_place_pending(self, p: dict) -> dict:
        with self.mt5_lock:
            mt5 = self.mt5
            symbol = p["symbol"]
            otype = int(p["order_type"])
            info = self._get_symbol(symbol)
            if info is None:
                return {"ok": False, "error": f"symbol not found: {symbol}",
                        "error_code": -2}
            price = float(p["price"])
            sl = float(p.get("sl") or 0.0)
            tp = float(p.get("tp") or 0.0)
            digits = int(getattr(info, "digits", 5))
            request = {
                "action": TRADE_ACTION_PENDING,
                "symbol": symbol,
                "volume": float(p["volume"]),
                "type": otype,
                "price": round(price, digits),
                "sl": round(sl, digits) if sl else 0.0,
                "tp": round(tp, digits) if tp else 0.0,
                "magic": int(p.get("magic", C.MAGIC_BASE)),
                "comment": str(p.get("comment", ""))[:31],
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": ORDER_FILLING_RETURN,
            }
            res, res_d = self._send_order(request)
            retcode = res_d.get("retcode", 0)
            if retcode != TRADE_RETCODE_PLACED and retcode != TRADE_RETCODE_DONE:
                return {"ok": False, "retcode": retcode, "error_code": retcode,
                        "error": C.RETCODES.get(retcode, f"retcode {retcode}")}
            # verify order exists
            orders = mt5.orders_get(ticket=res_d.get("order", 0)) or []
            verified = len(orders) > 0
            return {"ok": verified, "order": res_d.get("order", 0),
                    "error": "" if verified else "PENDING_UNVERIFIED"}

    def _act_modify_pending(self, p: dict) -> dict:
        with self.mt5_lock:
            ticket = int(p["slave_order_id"])
            request = {
                "action": TRADE_ACTION_MODIFY,
                "order": ticket,
                "price": round(float(p["price"]), int(p.get("digits", 5))),
                "sl": round(float(p.get("sl") or 0.0), int(p.get("digits", 5))),
                "tp": round(float(p.get("tp") or 0.0), int(p.get("digits", 5))),
            }
            res, res_d = self._send_order(request)
            retcode = res_d.get("retcode", 0)
            ok = retcode in (TRADE_RETCODE_DONE, TRADE_RETCODE_PLACED)
            return {"ok": ok, "retcode": retcode,
                    "error_code": retcode if not ok else 0,
                    "error": C.RETCODES.get(retcode) if not ok else ""}

    def _act_remove_pending(self, p: dict) -> dict:
        with self.mt5_lock:
            request = {"action": TRADE_ACTION_REMOVE,
                       "order": int(p["slave_order_id"])}
            res, res_d = self._send_order(request)
            retcode = res_d.get("retcode", 0)
            ok = retcode in (TRADE_RETCODE_DONE, TRADE_RETCODE_PLACED)
            return {"ok": ok, "retcode": retcode,
                    "error_code": retcode if not ok else 0,
                    "error": C.RETCODES.get(retcode) if not ok else ""}

    def _act_get_symbol_specs(self, p: dict) -> dict:
        with self.mt5_lock:
            out = []
            for symbol in p.get("symbols", []):
                info = self._get_symbol(symbol)
                if info is None:
                    continue
                out.append({
                    "symbol": symbol,
                    "digits": int(getattr(info, "digits", 5)),
                    "point": float(getattr(info, "point", 0.0)),
                    "tick_size": float(getattr(info, "trade_tick_size",
                                               getattr(info, "tick_size", 0.0)) or 0.0),
                    "spread_points": int(getattr(info, "spread", 0) or 0),
                    "trade_mode": int(getattr(info, "trade_mode", 0) or 0),
                    "trade_stops_level": int(getattr(info, "trade_stops_level", 0) or 0),
                    "trade_freeze_level": int(getattr(info, "trade_freeze_level", 0) or 0),
                    "filling_mode": int(getattr(info, "filling_mode", 0) or 0),
                    "volume_min": float(getattr(info, "volume_min", 0.0) or 0.0),
                    "volume_max": float(getattr(info, "volume_max", 0.0) or 0.0),
                    "volume_step": float(getattr(info, "volume_step", 0.0) or 0.0),
                    "contract_size": float(getattr(info, "contract_size", 0.0) or 0.0),
                    "trade_exec_mode": int(getattr(info, "trade_exemode", 0) or 0),
                })
            return {"ok": True, "specs": out}

    def _act_verify_position(self, p: dict) -> dict:
        with self.mt5_lock:
            ticket = int(p.get("slave_position_id", 0) or 0)
            order_ticket = int(p.get("slave_order_id", 0) or 0)
            poss = self.mt5.positions_get() or []
            for pos in poss:
                if ticket and int(pos.ticket) == ticket:
                    return {"ok": True, "found": True, "position": _nt_to_dict(pos)}
                if order_ticket and (int(pos.ticket) == order_ticket or
                                     int(getattr(pos, "identifier", 0)) == order_ticket):
                    return {"ok": True, "found": True, "position": _nt_to_dict(pos)}
            return {"ok": True, "found": False}


def run_worker(cfg: WorkerConfig, pipe_address: str) -> None:
    worker = Mt5Worker(cfg, pipe_address)
    worker.run()
