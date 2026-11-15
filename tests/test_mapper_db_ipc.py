"""Unit tests: symbol mapper + database dedup + IPC protocol roundtrip."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database.db import Database  # noqa: E402
from app.database.repository import Repository  # noqa: E402
from app.engine.symbol_mapper import SymbolMapper  # noqa: E402


def make_repo(tmp: str) -> Repository:
    repo = Repository(Database(os.path.join(tmp, "t.db")))
    # symbol_map has FK to terminals -> create test terminal rows
    for tid in ("t1", "t2", "t3"):
        repo.add_terminal(tid, f"Terminal {tid}", "C:/x/terminal64.exe")
    return repo


def test_symbol_mapper_exact_match(tmpdir=None):
    tmp = tempfile.mkdtemp()
    repo = make_repo(tmp)
    m = SymbolMapper(repo)
    slave_symbols = ["EURUSD.a", "GBPUSD", "XAUUSD.pro"]
    sym, status = m.resolve("t1", "EURUSD.a", slave_symbols)
    assert sym == "EURUSD.a" and status == "VERIFIED"


def test_symbol_mapper_suggestion_not_traded(tmpdir=None):
    tmp = tempfile.mkdtemp()
    repo = make_repo(tmp)
    m = SymbolMapper(repo)
    slave_symbols = ["EURUSD.m", "GBPUSD"]
    sym, status = m.resolve("t2", "EURUSD", slave_symbols)
    assert sym is None and status == "UNMAPPED"
    row = repo.get_symbol_map("t2", "EURUSD")
    assert row["status"] == "SUGGESTED" and row["slave_symbol"] == "EURUSD.m"


def test_symbol_mapper_manual_override(tmpdir=None):
    tmp = tempfile.mkdtemp()
    repo = make_repo(tmp)
    m = SymbolMapper(repo)
    m.set_manual("t3", "EURUSD", "EURUSD.m", verified=True)
    sym, status = m.resolve("t3", "EURUSD", ["EURUSD.m"])
    assert sym == "EURUSD.m" and status == "VERIFIED"


def test_event_dedup_in_db(tmpdir=None):
    tmp = tempfile.mkdtemp()
    repo = make_repo(tmp)
    ev = {
        "id": "e1", "event_key": "OPEN:123:456", "type": "POSITION_OPEN",
        "master_login": 111, "symbol": "EURUSD", "position_id": 123,
        "order_id": 456, "deal_id": 789, "side": "BUY", "volume": 0.1,
        "detected_at_ms": 1,
    }
    assert repo.insert_event(ev) is True
    ev2 = dict(ev)
    ev2["id"] = "e2"
    assert repo.insert_event(ev2) is False  # duplicate suppressed


def test_mapping_unique_per_slave(tmpdir=None):
    tmp = tempfile.mkdtemp()
    repo = make_repo(tmp)  # t1..t3 already created by helper
    repo.update_terminal("t1", role="MASTER")
    repo.insert_mapping(master_login=111, master_position_id=5001,
                        master_symbol="EURUSD", slave_terminal_id="t1",
                        slave_position_id=9001, slave_symbol="EURUSD",
                        status="OPEN", created_at_ms=1)
    import sqlite3
    try:
        repo.insert_mapping(master_login=111, master_position_id=5001,
                            master_symbol="EURUSD", slave_terminal_id="t1",
                            slave_position_id=9002, slave_symbol="EURUSD",
                            status="OPEN", created_at_ms=2)
        assert False, "unique constraint should fire"
    except sqlite3.IntegrityError:
        pass


def test_ipc_protocol_roundtrip():
    from app.ipc import protocol as P
    msg = P.snapshot("tid", {"login": 1, "positions": []}, {"build_ms": 1.2})
    assert msg["type"] == "snapshot"
    res = P.action_result("tid", "aid", ok=False, error="NO_MONEY",
                          error_code=10019, retcode=10019)
    assert res["retcode"] == 10019 and not res["ok"]


def test_ipc_transport_unix_roundtrip():
    """Full pipe roundtrip (works on Linux via AF_UNIX, on Windows via named
    pipes - same API)."""
    import threading

    from app.ipc.transport import (accept_blocking, connect_client, create_listener,
                                   make_address)
    addr = make_address("unittest-pipe")
    listener = create_listener(addr)
    got = {}

    def server():
        conn = accept_blocking(listener)
        assert conn is not None
        m = conn.recv(timeout=2)
        got["msg"] = m
        conn.send({"type": "reply", "ok": True})
        conn.close()

    t = threading.Thread(target=server, daemon=True)
    t.start()
    client = connect_client(addr)
    client.send({"type": "ping", "n": 1})
    reply = client.recv(timeout=2)
    t.join(timeout=5)
    listener.close()
    assert got["msg"] == {"type": "ping", "n": 1}
    assert reply == {"type": "reply", "ok": True}


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("mapper/db/ipc tests: ALL PASS")
