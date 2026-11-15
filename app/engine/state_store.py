"""Thread-safe state store: engine thread writes, UI thread reads."""
from __future__ import annotations

import threading
from collections import deque


class StateStore:
    def __init__(self, activity_max: int = 300):
        self._lock = threading.RLock()
        self._activity = deque(maxlen=activity_max)
        self.data: dict = {
            "engine_state": "STOPPED",
            "master": None,             # terminal row dict + snapshot
            "slaves": [],               # list of terminal dicts + snapshot + stats
            "stats": {
                "accounts_total": 0, "accounts_connected": 0,
                "slaves_active": 0, "master_open_positions": 0,
                "copied_total": 0, "failed_total": 0,
                "avg_copy_ms": None, "p95_copy_ms": None,
                "last_update_ms": 0,
            },
            "alerts": [],
            "language": "fa",
        }

    def update(self, **kwargs) -> None:
        with self._lock:
            self.data.update(kwargs)

    def get(self) -> dict:
        with self._lock:
            snap = dict(self.data)
            snap["alerts"] = list(self.data.get("alerts", []))
            return snap

    def add_activity(self, ts_ms: int, text: str, level: str = "info") -> None:
        with self._lock:
            self._activity.appendleft((ts_ms, level, text))

    def get_activity(self, limit: int = 120) -> list:
        with self._lock:
            return list(self._activity)[:limit]

    def add_alert(self, text: str) -> None:
        with self._lock:
            self.data.setdefault("alerts", []).append(text)

    def clear_alert(self, text: str) -> None:
        with self._lock:
            alerts = self.data.get("alerts", [])
            if text in alerts:
                alerts.remove(text)
