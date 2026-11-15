"""IPC transport: Windows Named Pipes (via multiprocessing.connection).

- Each terminal gets its own dedicated pipe, so one worker can never block
  another terminal's channel.
- Messages are JSON strings; both sides use send()/recv() framing provided
  by multiprocessing.connection (length-prefixed, robust over pipes).
- On Windows: family AF_PIPE (named pipes, current-user scoped).
  On other OS (dev/test): AF_UNIX in temp dir.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import uuid
from multiprocessing.connection import Listener

log = logging.getLogger("ipc")

AUTHKEY = b"TradingCopier-Local-IPC-v1"

if sys.platform == "win32":
    IPC_FAMILY = "AF_PIPE"
else:
    IPC_FAMILY = "AF_UNIX"


def make_address(terminal_id: str) -> str:
    if sys.platform == "win32":
        return f"\\\\.\\pipe\\TradingCopier\\{terminal_id}"
    return os.path.join("/tmp", f"tradingcopier_{terminal_id}.sock")


def create_listener(address: str) -> Listener:
    """Bind a fresh listener; raises OSError if the address is taken."""
    try:
        if IPC_FAMILY == "AF_UNIX" and os.path.exists(address):
            os.unlink(address)
        return Listener(address, family=IPC_FAMILY, authkey=AUTHKEY, backlog=2)
    except OSError as exc:
        raise OSError(f"Cannot bind IPC address {address}: {exc}") from exc


class MessageConnection:
    """Thread-safe wrapper around a multiprocessing.connection Connection
    carrying JSON dicts."""

    def __init__(self, conn):
        self._conn = conn
        self._send_lock = threading.Lock()
        self.peer = None

    def send(self, message: dict) -> None:
        data = json.dumps(message, ensure_ascii=False)
        with self._send_lock:
            self._conn.send(data)

    def recv(self, timeout: float = None):
        """Receive one message dict, or None on timeout/close."""
        if timeout is not None:
            if not self._conn.poll(timeout):
                return None
        try:
            raw = self._conn.recv()
        except (EOFError, OSError):
            return None
        try:
            msg = json.loads(raw)
            return msg if isinstance(msg, dict) else None
        except (json.JSONDecodeError, TypeError):
            log.warning("invalid IPC payload received")
            return None

    def recv_message(self, timeout: float = 0.5):
        """Returns (message_or_None, alive). alive=False means pipe is dead."""
        try:
            if not self._conn.poll(timeout):
                return None, True
        except (EOFError, OSError, ValueError):
            return None, False
        try:
            raw = self._conn.recv()
        except (EOFError, OSError):
            return None, False
        try:
            msg = json.loads(raw)
            return (msg if isinstance(msg, dict) else None), True
        except (json.JSONDecodeError, TypeError):
            log.warning("invalid IPC payload received")
            return None, True

    def poll(self, timeout: float = 0.0) -> bool:
        try:
            return self._conn.poll(timeout)
        except (EOFError, OSError):
            return False

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


def accept_blocking(listener: Listener):
    """Blocking accept; raises OSError/EOFError when the listener is closed."""
    return MessageConnection(listener.accept())


def connect_client(address: str, retries: int = 20, delay: float = 0.2):
    """Worker-side connect with retries."""
    from multiprocessing.connection import Client

    last_exc = None
    for _ in range(retries):
        try:
            conn = Client(address, family=IPC_FAMILY, authkey=AUTHKEY)
            return MessageConnection(conn)
        except (OSError, EOFError) as exc:
            last_exc = exc
            import time
            time.sleep(delay)
    raise ConnectionError(f"cannot connect IPC {address}: {last_exc}")


def new_action_id() -> str:
    return uuid.uuid4().hex
