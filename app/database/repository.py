"""Repository layer: all SQL access lives here."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from typing import Optional

from app.core.constants import LotMode, Role, SlTpMode
from app.core.utils import now_ms
from app.database.db import Database


class Repository:
    def __init__(self, db: Database):
        self.db = db

    # ---------------- terminals ----------------

    def add_terminal(self, tid: str, name: str, terminal_path: str, login=None,
                     server: str = None, role: str = Role.UNASSIGNED.value) -> str:
        self.db.execute(
            "INSERT INTO terminals(id,name,terminal_path,login,server,role) VALUES(?,?,?,?,?,?)",
            (tid, name, terminal_path, login, server, role),
        )
        self.db.execute(
            "INSERT OR IGNORE INTO slave_settings(terminal_id) VALUES(?)", (tid,)
        )
        return tid

    def update_terminal(self, tid: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE terminals SET {cols} WHERE id=?",
                        (*fields.values(), tid))

    def delete_terminal(self, tid: str) -> None:
        self.db.execute("DELETE FROM terminals WHERE id=?", (tid,))

    def get_terminals(self) -> list:
        return self.db.query("SELECT * FROM terminals ORDER BY created_at")

    def get_terminal(self, tid: str):
        return self.db.query_one("SELECT * FROM terminals WHERE id=?", (tid,))

    def get_master(self):
        return self.db.query_one("SELECT * FROM terminals WHERE role='MASTER' LIMIT 1")

    def get_slaves(self) -> list:
        return self.db.query("SELECT * FROM terminals WHERE role='SLAVE' ORDER BY created_at")

    # ---------------- slave settings ----------------

    DEFAULT_SLAVE_SETTINGS = {
        "copy_enabled": 1,
        "lot_mode": LotMode.MULTIPLIER.value,
        "lot_multiplier": 1.0,
        "fixed_lot": 0.01,
        "balance_ratio": 1.0,
        "equity_ratio": 1.0,
        "max_lot": None,
        "max_positions": None,
        "max_total_volume": None,
        "max_slippage_points": 50,
        "max_spread_points": None,
        "min_free_margin": None,
        "min_margin_level": None,
        "stop_if_equity_below": None,
        "copy_sl": 1,
        "copy_tp": 1,
        "sltp_mode": SlTpMode.ABSOLUTE.value,
        "allow_stops_adjust": 0,
        "copy_partial_close": 1,
        "copy_pending": 0,
        "pending_price_mode": "ABSOLUTE",
        "allowed_symbols": "",
        "allowed_directions": "BUY,SELL",
        "max_price_deviation_percent": 3.0,
        "auto_reconnect": 1,
    }

    def get_slave_settings(self, tid: str) -> dict:
        row = self.db.query_one("SELECT * FROM slave_settings WHERE terminal_id=?", (tid,))
        out = dict(self.DEFAULT_SLAVE_SETTINGS)
        if row:
            for k in out:
                if k in row.keys():
                    out[k] = row[k]
        return out

    def update_slave_settings(self, tid: str, **fields) -> None:
        allowed = set(self.DEFAULT_SLAVE_SETTINGS.keys())
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(
            f"UPDATE slave_settings SET {cols} WHERE terminal_id=?",
            (*fields.values(), tid),
        )

    # ---------------- symbol mapping ----------------

    def get_symbol_map(self, tid: str, master_symbol: str) -> Optional[sqlite3.Row]:
        return self.db.query_one(
            "SELECT * FROM symbol_map WHERE terminal_id=? AND master_symbol=?",
            (tid, master_symbol),
        )

    def upsert_symbol_map(self, tid: str, master_symbol: str, slave_symbol: Optional[str],
                          status: str, note: str = "") -> None:
        self.db.execute(
            """INSERT INTO symbol_map(terminal_id,master_symbol,slave_symbol,status,note,updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(terminal_id, master_symbol)
               DO UPDATE SET slave_symbol=excluded.slave_symbol,
                             status=excluded.status, note=excluded.note,
                             updated_at=excluded.updated_at""",
            (tid, master_symbol, slave_symbol, status, note, now_ms()),
        )

    def list_symbol_maps(self, tid: str) -> list:
        return self.db.query(
            "SELECT * FROM symbol_map WHERE terminal_id=? ORDER BY master_symbol", (tid,)
        )

    # ---------------- events ----------------

    def insert_event(self, ev: dict) -> bool:
        """Insert a detected master event. Returns False on duplicate event_key."""
        try:
            self.db.execute(
                """INSERT INTO events(id,event_key,type,master_login,master_symbol,
                    master_position_id,master_order_id,master_deal_id,side,volume,
                    volume_before,price,sl,tp,profit,payload,state,detected_at_ms)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ev["id"], ev["event_key"], ev["type"], ev["master_login"],
                    ev.get("symbol"), ev.get("position_id"), ev.get("order_id"),
                    ev.get("deal_id"), ev.get("side"), ev.get("volume"),
                    ev.get("volume_before"), ev.get("price"), ev.get("sl"),
                    ev.get("tp"), ev.get("profit"),
                    json.dumps(ev.get("payload", {}), ensure_ascii=False),
                    ev.get("state", "DETECTED"), ev.get("detected_at_ms", now_ms()),
                ),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def insert_synthetic_event(self, kind: str, detail: str = "") -> str:
        """Insert a system-initiated pseudo event (reconcile closes, manual
        bulk closes) so event_actions FK integrity holds."""
        eid = self.new_id()
        key = f"{kind}:{now_ms()}:{eid[:8]}"
        self.db.execute(
            "INSERT INTO events(id,event_key,type,master_login,state,"
            "detected_at_ms,payload) VALUES(?,?,?,?,?,?,?)",
            (eid, key, kind, 0, "VERIFIED", now_ms(),
             json.dumps({"detail": detail}, ensure_ascii=False)),
        )
        return eid

    def set_event_state(self, event_id: str, state: str) -> None:
        self.db.execute(
            "UPDATE events SET state=?, processed_at_ms=? WHERE id=?",
            (state, now_ms(), event_id),
        )

    # ---------------- event actions ----------------

    def insert_action(self, action_id: str, event_id: str, terminal_id: str,
                      params: dict, state: str = "QUEUED") -> None:
        self.db.execute(
            """INSERT INTO event_actions(id,event_id,terminal_id,state,params)
               VALUES(?,?,?,?,?)""",
            (action_id, event_id, terminal_id, state,
             json.dumps(params, ensure_ascii=False)),
        )

    def update_action(self, action_id: str, **fields) -> None:
        if not fields:
            return
        known = {"state", "attempts", "result", "error_code", "error_message",
                 "sent_at_ms", "completed_at_ms", "latency_detect_us", "latency_total_us"}
        fields = {k: v for k, v in fields.items() if k in known}
        if "result" in fields and not isinstance(fields["result"], (str, type(None))):
            fields["result"] = json.dumps(fields["result"], ensure_ascii=False)
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE event_actions SET {cols} WHERE id=?",
                        (*fields.values(), action_id))

    def get_action(self, action_id: str):
        return self.db.query_one("SELECT * FROM event_actions WHERE id=?", (action_id,))

    def list_actions_for_event(self, event_id: str) -> list:
        return self.db.query("SELECT * FROM event_actions WHERE event_id=?", (event_id,))

    def fail_stale_sent_actions(self, terminal_id: str, older_than_ms: int) -> list:
        """Actions stuck in SENT (worker died mid-flight) -> RECONCILIATION_REQUIRED."""
        rows = self.db.query(
            "SELECT id,event_id FROM event_actions WHERE terminal_id=? AND state='SENT'",
            (terminal_id,),
        )
        out = []
        for row in rows:
            if row["completed_at_ms"] is None and row["sent_at_ms"] is None:
                out.append(row)
                continue
            self.db.execute(
                "UPDATE event_actions SET state='RECONCILIATION_REQUIRED' WHERE id=?",
                (row["id"],),
            )
            out.append(row)
        return out

    # ---------------- copy mappings ----------------

    def insert_mapping(self, **fields) -> int:
        fields.setdefault("created_at_ms", now_ms())
        fields["updated_at_ms"] = now_ms()
        cols = ", ".join(fields.keys())
        marks = ", ".join("?" for _ in fields)
        cur = None
        with self.db.tx() as cur:
            cur.execute(f"INSERT INTO copy_mappings({cols}) VALUES({marks})",
                        tuple(fields.values()))
            return cur.lastrowid

    def update_mapping(self, mapping_id: int, **fields) -> None:
        if not fields:
            return
        fields["updated_at_ms"] = now_ms()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE copy_mappings SET {cols} WHERE id=?",
                        (*fields.values(), mapping_id))

    def get_mapping(self, master_position_id: int, slave_terminal_id: str):
        return self.db.query_one(
            "SELECT * FROM copy_mappings WHERE master_position_id=? AND slave_terminal_id=?",
            (master_position_id, slave_terminal_id),
        )

    def get_mapping_by_id(self, mapping_id: int):
        return self.db.query_one("SELECT * FROM copy_mappings WHERE id=?", (mapping_id,))

    def list_mappings(self, status: Optional[str] = None) -> list:
        if status:
            return self.db.query("SELECT * FROM copy_mappings WHERE status=?", (status,))
        return self.db.query("SELECT * FROM copy_mappings ORDER BY id DESC LIMIT 500")

    def list_open_mappings(self) -> list:
        return self.db.query(
            "SELECT * FROM copy_mappings WHERE status IN ('OPEN','PARTIAL','PENDING_ORDER')"
        )

    # ---------------- global settings ----------------

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.db.query_one("SELECT value FROM app_settings WHERE key=?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO app_settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def get_setting_int(self, key: str, default: int) -> int:
        try:
            return int(self.get_setting(key, str(default)))
        except (TypeError, ValueError):
            return default

    def get_setting_float(self, key: str, default: float) -> float:
        try:
            return float(self.get_setting(key, str(default)))
        except (TypeError, ValueError):
            return default

    # ---------------- misc ----------------

    def new_id(self) -> str:
        return uuid.uuid4().hex

    def count_open_positions_copied(self) -> int:
        row = self.db.query_one(
            "SELECT COUNT(*) AS c FROM copy_mappings WHERE status IN ('OPEN','PARTIAL')"
        )
        return row["c"] if row else 0


def default_data_dir() -> str:
    """%LOCALAPPDATA%\\TradingCopier on Windows; ~/.tradingcopier elsewhere."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return os.path.join(base, "TradingCopier")
    return os.path.expanduser("~/.tradingcopier")
