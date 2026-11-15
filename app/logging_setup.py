"""Structured logging with rotation.

- JSON-lines format for machine processing + readable console output.
- Rotating files in <data_dir>/logs, max 5 MB x 10 files.
- No passwords/secrets are ever passed to logging calls.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import time

_CONSOLE_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


class JsonLineFormatter(logging.Formatter):
    _RESERVED = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "taskName", "message",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                try:
                    json.dumps(value)
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = repr(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(data_dir: str, console: bool = True, level: str = "INFO") -> str:
    logs_dir = os.path.join(data_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_path = os.path.join(logs_dir, "tradingcopier.log")

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=10, encoding="utf-8"
    )
    file_handler.setFormatter(JsonLineFormatter())
    root.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(_CONSOLE_FMT))
        root.addHandler(console_handler)

    return log_path
