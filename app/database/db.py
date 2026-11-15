"""SQLite connection manager: WAL mode, single writer lock, safe transactions."""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager


class Database:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        cur = self._conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()
        self._apply_schema()

    def _apply_schema(self) -> None:
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        with open(schema_path, "r", encoding="utf-8") as fh:
            script = fh.read()
        with self.tx() as cur:
            cur.executescript(script)

    @contextmanager
    def tx(self):
        """Serialized transaction context; commits on success, rolls back on error."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("BEGIN IMMEDIATE")
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def execute(self, sql: str, params=()) -> None:
        with self.tx() as cur:
            cur.execute(sql, params)

    def query(self, sql: str, params=()) -> list:
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(sql, params)
                return cur.fetchall()
            finally:
                cur.close()

    def query_one(self, sql: str, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.commit()
            except Exception:
                pass
            self._conn.close()
