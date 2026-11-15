"""Application controller: owns workers, IPC, engine threads and state.

Threading model:
- main/UI thread: Qt only, never blocks.
- per-terminal listener thread: accepts the worker's pipe connection.
- engine thread: consumes incoming worker messages (queue), runs master
  analysis, copy dispatch, DB writes (single writer -> consistent state).
- watchdog thread: restarts crashed worker processes.
- reconciler thread: periodic reconciliation.

Engine state machine: STOPPED -> RUNNING <-> PAUSED -> EMERGENCY.
PAUSE blocks opening events, keeps managing copied positions.
STOP halts dispatch after in-flight completion. EMERGENCY blocks everything
immediately and reports in-flight operations.
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import os
import queue
import sqlite3
import threading
import time
import uuid
from typing import Optional

from app.core import constants as C
from app.core.utils import now_ms
from app.database.db import Database
from app.database.repository import Repository, default_data_dir
from app.engine.copy_engine import CopyEngine
from app.engine.master_analyzer import MasterAnalyzer
from app.engine.reconciler import Reconciler
from app.engine.state_store import StateStore
from app.engine.symbol_mapper import SymbolMapper
from app.ipc import protocol as P
from app.ipc.transport import (MessageConnection, accept_blocking,
                               create_listener, make_address)

log = logging.getLogger("controller")

RUNNING = True


class TerminalRuntime:
    def __init__(self, row: sqlite3.Row):
        self.terminal_id: str = row["id"]
        self.row: dict = dict(row)
        self.snapshot: Optional[dict] = None
        self.snapshot_ms: int = 0
        self.symbols: list[str] = []
        self.specs_cache: dict[str, dict] = {}
        self.conn: Optional[MessageConnection] = None
        self.listener = None
        self.proc = None
        self.hello: Optional[dict] = None
        self.last_status: str = "DISCONNECTED"
        self.blocked: bool = bool(row["blocked"]) if "blocked" in row.keys() else False
        self.latency_ms: float = 0.0

    @property
    def snapshot_age_ms(self) -> int:
        return now_ms() - self.snapshot_ms if self.snapshot else 10**9

    def is_connected(self) -> bool:
        return (self.conn is not None and self.snapshot is not None
                and self.snapshot_age_ms < 10000)


class AppController:
    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or default_data_dir()
        os.makedirs(self.data_dir, exist_ok=True)
        self.db = Database(os.path.join(self.data_dir, "data", "copier.db"))
        self.repo = Repository(self.db)
        self.store = StateStore()
        self.mapper = SymbolMapper(self.repo)
        self.copy_engine = CopyEngine(self.repo, self.mapper)
        self.reconciler = Reconciler(self.repo, self._send_action)

        self.runtimes: dict[str, TerminalRuntime] = {}
        self.engine_state: str = C.EngineState.STOPPED.value
        self.sync_existing_on_start: bool = False

        self._incoming: "queue.Queue[dict]" = queue.Queue(maxsize=10000)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._analyzer: Optional[MasterAnalyzer] = None
        self._latencies_ms: list[float] = []
        self._master_snapshot: Optional[dict] = None
        self._startup_ms = now_ms()
        self._recon_running = threading.Event()

        # single-instance guard via guard pipe (Windows-only benefit; on other
        # platforms it still works through the address binding)
        self._guard_listener = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        self._guard()
        for row in self.repo.get_terminals():
            rt = TerminalRuntime(row)
            rt.row["settings"] = self.repo.get_slave_settings(rt.terminal_id)
            self.runtimes[rt.terminal_id] = rt
        lang = self.repo.get_setting("language", "fa")
        self.engine_state = self.repo.get_setting("engine_state",
                                                  C.EngineState.STOPPED.value)
        if self.engine_state == C.EngineState.RUNNING.value:
            # never auto-resume copying after a restart; require explicit START
            self.engine_state = C.EngineState.STOPPED.value
        self.store.update(language=lang, engine_state=self.engine_state)

        self._start_all_workers()
        self._spawn_thread(self._engine_loop, "engine")
        self._spawn_thread(self._watchdog_loop, "watchdog")
        self._spawn_thread(self._reconcile_loop, "reconciler")
        log.info("controller initialized with %d terminals",
                 len(self.runtimes))

    def _guard(self) -> None:
        """Try to bind a guard address; exit flow if another instance runs."""
        try:
            addr = make_address("__guard__")
            self._guard_listener = create_listener(addr)
        except OSError:
            log.error("another instance is already running")
            raise SystemExit("Trading Copier is already running.")

    def shutdown(self) -> None:
        self._stop.set()
        for rt in self.runtimes.values():
            try:
                if rt.conn is not None:
                    rt.conn.send(P.shutdown())
            except Exception:
                pass
            try:
                if rt.proc is not None and rt.proc.is_alive():
                    rt.proc.join(timeout=2)
                    if rt.proc.is_alive():
                        rt.proc.terminate()
            except Exception:
                pass
            try:
                if rt.listener is not None:
                    rt.listener.close()
            except Exception:
                pass
        try:
            if self._guard_listener:
                self._guard_listener.close()
        except Exception:
            pass
        self.repo.set_setting("engine_state", C.EngineState.STOPPED.value)
        self.db.close()
        log.info("controller shut down")

    # ------------------------------------------------------------------
    # workers management
    # ------------------------------------------------------------------

    def _start_all_workers(self) -> None:
        for rt in self.runtimes.values():
            self._start_worker(rt)

    def _start_worker(self, rt: TerminalRuntime) -> None:
        if rt.listener is None:
            try:
                rt.listener = create_listener(make_address(rt.terminal_id))
            except OSError as exc:
                log.error("cannot bind listener for %s: %s", rt.terminal_id, exc)
                return
            self._spawn_thread(lambda rt=rt: self._listener_loop(rt),
                               f"listener-{rt.terminal_id[:8]}")
        self._spawn_worker_process(rt)

    def _spawn_worker_process(self, rt: TerminalRuntime) -> None:
        if rt.proc is not None and rt.proc.is_alive():
            return
        settings = rt.row.get("settings") or self.repo.get_slave_settings(rt.terminal_id)
        password = None
        if rt.row.get("enc_password"):
            try:
                from app.security.dpapi import unprotect_from_str
                password = unprotect_from_str(
                    rt.row["enc_password"] if isinstance(rt.row["enc_password"], str)
                    else rt.row["enc_password"].decode("ascii")).decode("utf-8")
            except Exception as exc:
                log.warning("cannot decrypt stored password: %s", exc)
        cfg = {
            "terminal_id": rt.terminal_id,
            "terminal_path": rt.row["terminal_path"],
            "login": rt.row.get("login"),
            "password": password,
            "server": rt.row.get("server"),
            "is_master": rt.row.get("role") == C.Role.MASTER.value,
            "poll_ms_master": self.repo.get_setting_int("poll_ms_master", 50),
            "poll_ms_slave": self.repo.get_setting_int("poll_ms_slave", 250),
            "deal_window_sec": self.repo.get_setting_int("deal_window_sec", 600),
            "slippage_points": settings.get("max_slippage_points", 50),
            "precheck_margin": bool(self.repo.get_setting_int("precheck_margin", 1)),
        }
        from app.workers.worker_main import worker_process_entry
        ctx = mp.get_context("spawn")
        rt.proc = ctx.Process(target=worker_process_entry,
                              args=(cfg, make_address(rt.terminal_id)),
                              daemon=True, name=f"worker-{rt.terminal_id[:8]}")
        rt.proc.start()
        rt.last_status = "CONNECTING"

    def _listener_loop(self, rt: TerminalRuntime) -> None:
        """Accept worker connections on this terminal's dedicated pipe.

        Keeps accepting forever (a reconnected worker must be able to
        re-attach); unblocked at shutdown by listener.close().
        """
        while not self._stop.is_set():
            try:
                conn = accept_blocking(rt.listener)
            except (OSError, EOFError, AttributeError):
                return  # listener closed -> shutdown
            rt.conn = conn
            self._incoming.put({"type": "_internal", "kind": "pipe_connected",
                                "terminal_id": rt.terminal_id})
            # drain this connection until the pipe dies
            while not self._stop.is_set():
                msg, alive = conn.recv_message(timeout=0.5)
                if not alive:
                    break
                if msg is None:
                    continue
                msg["terminal_id"] = msg.get("terminal_id") or rt.terminal_id
                try:
                    self._incoming.put_nowait(msg)
                except queue.Full:
                    log.error("incoming queue full; dropping %s", msg.get("type"))
            rt.conn = None
            self._incoming.put({"type": "_internal", "kind": "pipe_lost",
                                "terminal_id": rt.terminal_id})
            # loop back to accept the respawned worker's connection

    def _watchdog_loop(self) -> None:
        while not self._stop.is_set():
            for rt in list(self.runtimes.values()):
                if rt.proc is None or not rt.proc.is_alive():
                    settings = rt.row.get("settings") or {}
                    if settings.get("auto_reconnect", 1):
                        log.info("watchdog respawning worker %s",
                                 rt.terminal_id[:8])
                        try:
                            self._spawn_worker_process(rt)
                        except Exception:
                            log.exception("respawn failed for %s",
                                          rt.terminal_id[:8])
            self._stop.wait(3.0)

    # ------------------------------------------------------------------
    # engine loop
    # ------------------------------------------------------------------

    def _spawn_thread(self, target, name: str) -> None:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self._threads.append(t)

    def _engine_loop(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self._incoming.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                self._handle_message(msg)
            except Exception:
                log.exception("engine message handling failed: %r", msg)

    def _handle_message(self, msg: dict) -> None:
        mtype = msg.get("type")
        tid = msg.get("terminal_id")
        if mtype == "_internal":
            rt = self.runtimes.get(tid)
            if rt is not None:
                rt.last_status = ("CONNECTED" if msg["kind"] == "pipe_connected"
                                  else "DISCONNECTED")
                if msg["kind"] == "pipe_lost":
                    self._fail_stale_actions(rt)
            self._publish_state()
            return
        rt = self.runtimes.get(tid)
        if rt is None:
            return

        if mtype == P.MSG_HELLO:
            self._on_hello(rt, msg)
        elif mtype == P.MSG_SNAPSHOT:
            self._on_snapshot(rt, msg)
        elif mtype == P.MSG_ACTION_RESULT:
            self._on_action_result(rt, msg)
        elif mtype == P.MSG_STATUS:
            rt.last_status = msg.get("state", "UNKNOWN")
            if msg.get("message"):
                self.store.add_activity(now_ms(),
                                        f"[{rt.row['name']}] {msg['message']}",
                                        "warn")
            self._publish_state()
        elif mtype == P.MSG_SYMBOLS_SPECS:
            for spec in msg.get("specs", []):
                rt.specs_cache[spec["symbol"]] = spec

    def _on_hello(self, rt: TerminalRuntime, msg: dict) -> None:
        rt.hello = msg
        rt.symbols = msg.get("symbols", []) or []
        account = msg.get("account") or {}
        if msg.get("ok"):
            login = int(account.get("login", 0) or 0)
            server = str(account.get("server", ""))
            reg_login = rt.row.get("login")
            reg_server = rt.row.get("server")
            if not reg_login and login:
                # first hello: adopt the terminal's current session identity
                self.repo.update_terminal(rt.terminal_id, login=login, server=server)
                rt.row["login"], rt.row["server"] = login, server
                reg_login, reg_server = login, server
            # account-change detection: login+server must match the registered
            # terminal identity
            if reg_login and reg_server and \
                    (login != reg_login or server != reg_server):
                rt.blocked = True
                self.repo.update_terminal(rt.terminal_id, blocked=1)
                alert = (f"ACCOUNT CHANGED on {rt.row['name']}: "
                         f"{reg_login}@{reg_server} -> {login}@{server}; "
                         "copy stopped for this terminal.")
                self.store.add_alert(alert)
                self.store.add_activity(now_ms(), alert, "error")
                log.warning(alert)
            else:
                self.repo.update_terminal(
                    rt.terminal_id,
                    account_currency=account.get("currency"),
                    account_name=account.get("name"),
                    leverage=account.get("leverage"),
                    mt5_version=msg.get("mt5_version"),
                    trade_allowed=int(bool(account.get("trade_allowed"))),
                    algo_allowed=int(bool(account.get("terminal_trade_allowed"))),
                    last_connected_at=time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime()),
                    last_error=None,
                )
                rt.row.update({
                    "account_currency": account.get("currency"),
                    "account_name": account.get("name"),
                })
            # proactively cache specs for mapped symbols
            maps = self.repo.list_symbol_maps(rt.terminal_id)
            want = [m["slave_symbol"] for m in maps if m["slave_symbol"]]
            self._send_action(rt.terminal_id, uuid.uuid4().hex,
                              P.ACT_GET_SYMBOL_SPECS, {"symbols": want})
        else:
            err = msg.get("error") or "terminal not logged in"
            self.repo.update_terminal(rt.terminal_id, last_error=err)
            self.store.add_activity(now_ms(),
                                    f"[{rt.row['name']}] connect failed: {err}",
                                    "error")
        self._publish_state()

    def _on_snapshot(self, rt: TerminalRuntime, msg: dict) -> None:
        snap = msg.get("snapshot") or {}
        rt.snapshot = snap
        rt.snapshot_ms = now_ms()
        rt.latency_ms = float((msg.get("latencies") or {}).get("build_ms", 0.0))

        # account drift detection on every snapshot (cheap)
        reg_login = rt.row.get("login")
        if reg_login and snap.get("login") and int(snap["login"]) != int(reg_login):
            if not rt.blocked:
                rt.blocked = True
                self.repo.update_terminal(rt.terminal_id, blocked=1)
                self.store.add_alert(
                    f"ACCOUNT CHANGED on {rt.row['name']}: copy stopped.")

        if rt.row.get("role") == C.Role.MASTER.value:
            self._master_snapshot = snap
            self._on_master_snapshot(snap)
        self._publish_state()

    def _on_master_snapshot(self, snap: dict) -> None:
        if self._analyzer is None:
            self._analyzer = MasterAnalyzer(int(snap.get("login", 0) or 0))
        events = self._analyzer.analyze(snap)
        if not events:
            return
        master_login = int(snap.get("login", 0) or 0)
        slave_rts = self._active_slave_runtimes()
        for ev in events:
            self._dispatch_event(ev, master_login, slave_rts, snap)
        # ask for newly requested specs
        for rt in slave_rts:
            want = rt.pop("request_specs", None)
            if want:
                self._send_action(rt.terminal_id, uuid.uuid4().hex,
                                  P.ACT_GET_SYMBOL_SPECS, {"symbols": want})

    def _active_slave_runtimes(self) -> list[dict]:
        out = []
        for rt in self.runtimes.values():
            if rt.row.get("role") != C.Role.SLAVE.value or rt.blocked:
                continue
            settings = rt.row.get("settings") or self.repo.get_slave_settings(
                rt.terminal_id)
            out.append({
                "terminal_id": rt.terminal_id,
                "settings": settings,
                "snapshot": rt.snapshot,
                "snapshot_age_ms": rt.snapshot_age_ms,
                "symbols": rt.symbols,
                "specs_cache": rt.specs_cache,
                "open_positions_count": len(rt.snapshot.get("positions", []))
                if rt.snapshot else 0,
                "open_total_volume": sum(float(p.get("volume", 0.0))
                                         for p in rt.snapshot.get("positions", []))
                if rt.snapshot else 0.0,
            })
        return out

    def _dispatch_event(self, ev: dict, master_login: int,
                        slave_rts: list[dict], master_snap: dict) -> None:
        t0 = time.perf_counter()
        state = self.copy_engine.plan_and_dispatch(
            ev, master_snap, slave_rts, self._send_action, self.engine_state,
            master_balance=float(master_snap.get("balance", 0.0)),
            master_equity=float(master_snap.get("equity", 0.0)))
        dur_us = int((time.perf_counter() - t0) * 1_000_000)
        label = (f"MASTER {ev.get('side','')} {ev.get('symbol','')} "
                 f"{ev.get('volume','')} {ev['type'].replace('POSITION_', '')}"
                 + (f" -> {state}" if state != C.EventState.VERIFIED.value else ""))
        self.store.add_activity(ev["detected_at_ms"], label,
                                "info" if state not in (
                                    C.EventState.FAILED.value,) else "error")
        log.info("event %s %s dispatched in %dus", ev["type"],
                 ev["event_key"], dur_us)

    def _on_action_result(self, rt: TerminalRuntime, msg: dict) -> None:
        action_id = msg["action_id"]
        now = now_ms()
        sent_ms = None
        if action := self.repo.get_action(action_id):
            sent_ms = action["sent_at_ms"]
        total_us = int((now - sent_ms) * 1000) if sent_ms else 0
        self.copy_engine.on_action_result(
            action_id, bool(msg.get("ok")), msg.get("data") or {},
            msg.get("error", ""), int(msg.get("error_code") or 0),
            int(msg.get("retcode") or 0), msg.get("latencies") or {}, total_us)
        ok = bool(msg.get("ok"))
        self.store.add_activity(
            now,
            f"[{rt.row['name']}] {('OK' if ok else 'FAIL: ' + msg.get('error', ''))} "
            f"({total_us/1000:.1f}ms)",
            "info" if ok else "error")
        if not ok:
            self.store.add_alert(f"Copy action failed on {rt.row['name']}: "
                                 f"{msg.get('error', 'unknown')}")
        self._publish_state()

    def _fail_stale_actions(self, rt: TerminalRuntime) -> None:
        for row in self.repo.fail_stale_sent_actions(rt.terminal_id, 0):
            self.store.add_activity(
                now_ms(),
                f"[{rt.row['name']}] in-flight action lost -> needs reconciliation",
                "warn")

    # ------------------------------------------------------------------
    # reconcile loop
    # ------------------------------------------------------------------

    def _reconcile_loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(30)
            if self._stop.is_set():
                return
            if self._recon_running.is_set():
                continue
            self._recon_running.set()
            try:
                master_positions = {}
                if self._master_snapshot:
                    master_positions = {
                        int(p["ticket"]): p
                        for p in self._master_snapshot.get("positions", [])}
                slave_rts = {tid: {"snapshot": rt.snapshot}
                             for tid, rt in self.runtimes.items()}
                findings = self.reconciler.run(
                    0, master_positions, slave_rts)
                for f in findings:
                    self.store.add_activity(now_ms(), f, "warn")
            except Exception:
                log.exception("reconciliation cycle failed")
            finally:
                self._recon_running.clear()

    # ------------------------------------------------------------------
    # action sending
    # ------------------------------------------------------------------

    def _send_action(self, terminal_id: str, action_id: str,
                     action_type: str, params: dict) -> bool:
        rt = self.runtimes.get(terminal_id)
        if rt is None or rt.conn is None:
            return False
        try:
            rt.conn.send(P.action(action_id, action_type, params))
            return True
        except (OSError, EOFError, ValueError):
            rt.conn = None
            return False

    # ------------------------------------------------------------------
    # public API (called from UI thread)
    # ------------------------------------------------------------------

    def add_terminal(self, name: str, path: str, login=None, server=None,
                     password: Optional[str] = None) -> str:
        tid = uuid.uuid4().hex
        role = C.Role.UNASSIGNED.value
        existing_master = self.repo.get_master()
        if existing_master is None:
            role = C.Role.MASTER.value
        self.repo.add_terminal(tid, name, path, login, server, role)
        rt = TerminalRuntime(self.repo.get_terminal(tid))
        rt.row["settings"] = self.repo.get_slave_settings(tid)
        if password:
            try:
                from app.security.dpapi import protect_to_str
                self.repo.db.execute(
                    "UPDATE terminals SET enc_password=? WHERE id=?",
                    (protect_to_str(password.encode("utf-8")), tid))
            except Exception as exc:
                log.warning("DPAPI unavailable; password not stored: %s", exc)
        self.runtimes[tid] = rt
        self._start_worker(rt)
        self._publish_state()
        return tid

    def delete_terminal(self, tid: str) -> None:
        rt = self.runtimes.pop(tid, None)
        if rt:
            try:
                if rt.conn:
                    rt.conn.send(P.shutdown())
            except Exception:
                pass
            try:
                if rt.proc and rt.proc.is_alive():
                    rt.proc.terminate()
            except Exception:
                pass
            try:
                if rt.listener:
                    rt.listener.close()
            except Exception:
                pass
        self.repo.delete_terminal(tid)
        if self._analyzer is not None:
            self._analyzer = None
        self._publish_state()

    def set_master(self, tid: str) -> None:
        """Changing master: stop copying safely first."""
        self.stop_copying()
        old = self.repo.get_master()
        if old is not None and old["id"] != tid:
            self.repo.update_terminal(old["id"], role=C.Role.UNASSIGNED.value)
            if old["id"] in self.runtimes:
                self.runtimes[old["id"]].row["role"] = C.Role.UNASSIGNED.value
        self.repo.update_terminal(tid, role=C.Role.MASTER.value)
        if tid in self.runtimes:
            self.runtimes[tid].row["role"] = C.Role.MASTER.value
            self.runtimes[tid].row["blocked"] = 0
        # reconfigure workers (master poll rate)
        for rt in self.runtimes.values():
            try:
                if rt.conn:
                    rt.conn.send(P.configure(
                        self.repo.get_setting_int("poll_ms_master", 50),
                        self.repo.get_setting_int("poll_ms_slave", 250),
                        self.repo.get_setting_int("deal_window_sec", 600)))
            except Exception:
                pass
        self._analyzer = None
        self.store.add_activity(now_ms(), "MASTER set; copying stopped "
                                           "(press START to begin)", "warn")
        self._publish_state()

    def set_slave(self, tid: str) -> None:
        master = self.repo.get_master()
        if master is not None and master["id"] == tid:
            raise ValueError("terminal is the MASTER; unset master first")
        self.repo.update_terminal(tid, role=C.Role.SLAVE.value)
        if tid in self.runtimes:
            self.runtimes[tid].row["role"] = C.Role.SLAVE.value
        self._publish_state()

    def unassign(self, tid: str) -> None:
        self.repo.update_terminal(tid, role=C.Role.UNASSIGNED.value)
        if tid in self.runtimes:
            self.runtimes[tid].row["role"] = C.Role.UNASSIGNED.value
        self._publish_state()

    def update_slave_settings(self, tid: str, **fields) -> None:
        self.repo.update_slave_settings(tid, **fields)
        if tid in self.runtimes:
            self.runtimes[tid].row["settings"] = self.repo.get_slave_settings(tid)

    def set_global_setting(self, key: str, value: str) -> None:
        self.repo.set_setting(key, value)

    # ----- engine controls -----

    def start_copying(self, sync_existing: bool = False) -> None:
        master = self.repo.get_master()
        if master is None:
            raise ValueError("no MASTER selected")
        self.sync_existing_on_start = sync_existing
        self.engine_state = C.EngineState.RUNNING.value
        self.repo.set_setting("engine_state", self.engine_state)
        if sync_existing and self._master_snapshot:
            self._sync_existing_master_positions()
        self.store.add_activity(now_ms(), "COPYING STARTED", "info")
        self._publish_state()

    def _sync_existing_master_positions(self) -> None:
        """Copy already-open master positions (requires explicit user opt-in)."""
        if not self._master_snapshot:
            return
        for p in self._master_snapshot.get("positions", []):
            pid = int(p["ticket"])
            already = any(self.repo.get_mapping(pid, tid)
                          for tid in self.runtimes)
            if already:
                continue
            ev = {
                "type": C.EventType.POSITION_OPEN.value,
                "event_key": f"OPEN:{pid}:sync:{self._startup_ms}",
                "master_login": int(self._master_snapshot.get("login", 0)),
                "symbol": p.get("symbol"),
                "position_id": pid,
                "side": "BUY" if int(p.get("type", 0)) == 0 else "SELL",
                "volume": float(p.get("volume", 0.0)),
                "price": float(p.get("price_open", 0.0)),
                "sl": float(p.get("sl", 0.0) or 0.0),
                "tp": float(p.get("tp", 0.0) or 0.0),
                "detected_at_ms": now_ms(),
                "payload": {"sync_existing": True},
            }
            self._dispatch_event(ev, ev["master_login"],
                                 self._active_slave_runtimes(),
                                 self._master_snapshot)

    def pause_copying(self) -> None:
        self.engine_state = C.EngineState.PAUSED.value
        self.repo.set_setting("engine_state", self.engine_state)
        self.store.add_activity(now_ms(), "COPYING PAUSED "
                                           "(new trades blocked, management continues)",
                                "warn")
        self._publish_state()

    def resume_copying(self) -> None:
        if self.engine_state != C.EngineState.PAUSED.value:
            return
        self.engine_state = C.EngineState.RUNNING.value
        self.repo.set_setting("engine_state", self.engine_state)
        self.store.add_activity(now_ms(), "COPYING RESUMED", "info")
        self._publish_state()

    def stop_copying(self) -> None:
        self.engine_state = C.EngineState.STOPPED.value
        self.repo.set_setting("engine_state", self.engine_state)
        self.store.add_activity(now_ms(), "COPYING STOPPED", "warn")
        self._publish_state()

    def emergency_stop(self) -> None:
        self.engine_state = C.EngineState.EMERGENCY.value
        self.repo.set_setting("engine_state", self.engine_state)
        self.store.add_activity(now_ms(), "EMERGENCY STOP ENGAGED", "error")
        self._publish_state()

    def close_all_copied_positions(self) -> int:
        """Close ONLY positions owned by the copy engine (mapped ones).
        Manual master/slave trades are never touched. Returns count sent."""
        sent = 0
        for m in self.repo.list_open_mappings():
            if not m["slave_position_id"]:
                continue
            tid = m["slave_terminal_id"]
            action_id = uuid.uuid4().hex
            ev_id = self.repo.insert_synthetic_event(
                "MANUAL_CLOSE_ALL", f"mapping {m['id']}")
            self.repo.insert_action(action_id, ev_id, tid,
                                    {"slave_position_id": m["slave_position_id"],
                                     "_manual_close_all": True})
            if self._send_action(tid, action_id, "close_full",
                                 {"slave_position_id": m["slave_position_id"]}):
                self.repo.update_action(action_id, state=C.ActionState.SENT.value,
                                        sent_at_ms=now_ms())
                self.repo.update_mapping(m["id"],
                                         status=C.MappingStatus.CLOSED.value)
                sent += 1
        self.store.add_activity(now_ms(),
                                f"CLOSE COPIED POSITIONS: {sent} close orders sent",
                                "warn")
        return sent

    # ------------------------------------------------------------------
    # state publishing
    # ------------------------------------------------------------------

    def _publish_state(self) -> None:
        master_rt = None
        slaves = []
        connected = 0
        slaves_active = 0
        for rt in self.runtimes.values():
            entry = {
                "terminal_id": rt.terminal_id,
                "name": rt.row.get("name"),
                "login": rt.row.get("login"),
                "server": rt.row.get("server"),
                "role": rt.row.get("role"),
                "blocked": rt.blocked,
                "connected": rt.is_connected(),
                "status": rt.last_status,
                "last_error": rt.row.get("last_error"),
                "currency": rt.row.get("account_currency"),
                "snapshot": rt.snapshot,
                "snapshot_age_ms": rt.snapshot_age_ms if rt.snapshot else None,
                "worker_latency_ms": rt.latency_ms,
                "settings": rt.row.get("settings") or {},
                "mt5_version": rt.row.get("mt5_version"),
                "trade_allowed": rt.row.get("trade_allowed"),
                "algo_allowed": rt.row.get("algo_allowed"),
            }
            if rt.row.get("role") == C.Role.MASTER.value:
                master_rt = entry
            else:
                settings = rt.row.get("settings") or {}
                entry["copy_enabled"] = bool(settings.get("copy_enabled"))
                slaves.append(entry)
            if rt.is_connected():
                connected += 1
            if rt.row.get("role") == C.Role.SLAVE.value and \
                    (rt.row.get("settings") or {}).get("copy_enabled") and \
                    not rt.blocked:
                slaves_active += 1
        stats = {
            "accounts_total": len(self.runtimes),
            "accounts_connected": connected,
            "slaves_active": slaves_active,
            "master_open_positions": len(
                self._master_snapshot.get("positions", []))
            if self._master_snapshot else 0,
            "copied_total": self._count_copied(),
            "failed_total": self._count_failed(),
            "avg_copy_ms": (round(sum(self._latencies_ms) / len(self._latencies_ms), 1)
                            if self._latencies_ms else None),
            "p95_copy_ms": self._p95(),
            "last_update_ms": now_ms(),
        }
        self.store.update(engine_state=self.engine_state, master=master_rt,
                          slaves=slaves, stats=stats)

    def _count_copied(self) -> int:
        row = self.repo.db.query_one(
            "SELECT COUNT(*) AS c FROM copy_mappings WHERE "
            "status IN ('OPEN','PARTIAL','CLOSED')")
        return row["c"] if row else 0

    def _count_failed(self) -> int:
        row = self.repo.db.query_one(
            "SELECT COUNT(*) AS c FROM event_actions WHERE state='FAILED'")
        return row["c"] if row else 0

    def _p95(self) -> Optional[float]:
        if len(self._latencies_ms) < 10:
            return None
        data = sorted(self._latencies_ms)
        idx = int(len(data) * 0.95) - 1
        return round(data[max(0, idx)], 1)

    def note_copy_latency(self, ms: float) -> None:
        self._latencies_ms.append(ms)
        if len(self._latencies_ms) > 200:
            self._latencies_ms.pop(0)

    # ------------------------------------------------------------------
    # helpers for UI
    # ------------------------------------------------------------------

    def list_symbol_maps(self, tid: str):
        return self.repo.list_symbol_maps(tid)

    def set_symbol_map(self, tid: str, master_symbol: str,
                       slave_symbol, verified: bool = True) -> None:
        self.mapper.set_manual(tid, master_symbol, slave_symbol, verified)
        rt = self.runtimes.get(tid)
        if rt is not None and slave_symbol:
            self._send_action(tid, uuid.uuid4().hex, P.ACT_GET_SYMBOL_SPECS,
                              {"symbols": [slave_symbol]})

    def get_positions_view(self) -> list[dict]:
        """Live positions across all accounts for the UI table."""
        out = []
        mappings_by_slave: dict[tuple, dict] = {}
        for m in self.repo.list_open_mappings():
            mappings_by_slave[(m["slave_terminal_id"], m["slave_position_id"])] = dict(m)
        for rt in self.runtimes.values():
            snap = rt.snapshot
            if not snap:
                continue
            role = rt.row.get("role")
            for p in snap.get("positions", []):
                mapping = mappings_by_slave.get((rt.terminal_id,
                                                 int(p.get("ticket", 0))))
                out.append({
                    "terminal_id": rt.terminal_id,
                    "account": rt.row.get("name"),
                    "role": role,
                    "symbol": p.get("symbol"),
                    "ticket": p.get("ticket"),
                    "type": "BUY" if int(p.get("type", 0)) == 0 else "SELL",
                    "volume": p.get("volume"),
                    "price_open": p.get("price_open"),
                    "price_current": p.get("price_current"),
                    "sl": p.get("sl"),
                    "tp": p.get("tp"),
                    "profit": p.get("profit"),
                    "swap": p.get("swap"),
                    "is_copied": mapping is not None,
                    "master_position_ref":
                        mapping["master_position_id"] if mapping else None,
                })
        return out
