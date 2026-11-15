"""IPC message protocol (worker <-> controller). All messages are JSON dicts
with a "type" field. Keep payloads small; snapshots are the biggest ones."""
from __future__ import annotations

# worker -> controller
MSG_HELLO = "hello"              # worker registered, account/terminal meta
MSG_SNAPSHOT = "snapshot"        # periodic account/positions/orders/deals
MSG_ACTION_RESULT = "action_result"
MSG_STATUS = "status"            # connection state / errors
MSG_SYMBOLS_SPECS = "symbol_specs"  # answer to get_symbol_specs / specs push

# controller -> worker
MSG_CONFIGURE = "configure"      # poll rates / flags
MSG_ACTION = "action"
MSG_SHUTDOWN = "shutdown"


# ---------- worker -> controller builders ----------

def hello(terminal_id: str, ok: bool, account: dict = None, symbols: list = None,
          mt5_version: str = "", error: str = "", pid: int = 0) -> dict:
    return {
        "type": MSG_HELLO, "terminal_id": terminal_id, "ok": ok,
        "account": account or {}, "symbols": symbols or [],
        "mt5_version": mt5_version, "error": error, "pid": pid,
    }


def snapshot(terminal_id: str, data: dict, worker_latencies: dict) -> dict:
    return {
        "type": MSG_SNAPSHOT, "terminal_id": terminal_id,
        "snapshot": data, "latencies": worker_latencies,
    }


def action_result(terminal_id: str, action_id: str, ok: bool, data: dict = None,
                  error: str = "", error_code: int = 0, retcode: int = 0,
                  latencies: dict = None) -> dict:
    return {
        "type": MSG_ACTION_RESULT, "terminal_id": terminal_id,
        "action_id": action_id, "ok": ok, "data": data or {},
        "error": error, "error_code": error_code, "retcode": retcode,
        "latencies": latencies or {},
    }


def status(terminal_id: str, state: str, message: str = "") -> dict:
    return {"type": MSG_STATUS, "terminal_id": terminal_id,
            "state": state, "message": message}


def symbol_specs(terminal_id: str, specs: list) -> dict:
    return {"type": MSG_SYMBOLS_SPECS, "terminal_id": terminal_id, "specs": specs}


# ---------- controller -> worker builders ----------

def configure(poll_ms_master: int, poll_ms_slave: int, deal_window_sec: int) -> dict:
    return {"type": MSG_CONFIGURE, "poll_ms_master": poll_ms_master,
            "poll_ms_slave": poll_ms_slave, "deal_window_sec": deal_window_sec}


def action(action_id: str, action_type: str, params: dict) -> dict:
    return {"type": MSG_ACTION, "action_id": action_id,
            "action_type": action_type, "params": params}


def shutdown() -> dict:
    return {"type": MSG_SHUTDOWN}


# ---------- action types (controller -> worker) ----------

ACT_OPEN_POSITION = "open_position"
ACT_MODIFY_SLTP = "modify_sltp"
ACT_CLOSE_FULL = "close_full"
ACT_CLOSE_PARTIAL = "close_partial"
ACT_PLACE_PENDING = "place_pending"
ACT_MODIFY_PENDING = "modify_pending"
ACT_REMOVE_PENDING = "remove_pending"
ACT_GET_SYMBOL_SPECS = "get_symbol_specs"
ACT_VERIFY_POSITION = "verify_position"
