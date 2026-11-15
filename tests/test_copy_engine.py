"""Integration test: full copy-engine flow against a real SQLite DB.

Event -> plan -> dispatch -> worker result -> mapping + dedup.
No MT5, no orders - send_fn is a stub (records dispatches).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core import constants as C  # noqa: E402
from app.database.db import Database  # noqa: E402
from app.database.repository import Repository  # noqa: E402
from app.engine.copy_engine import CopyEngine  # noqa: E402
from app.engine.symbol_mapper import SymbolMapper  # noqa: E402


def setup_engine():
    tmp = tempfile.mkdtemp()
    repo = Repository(Database(os.path.join(tmp, "t.db")))
    repo.add_terminal("master1", "Master", "C:/x1/terminal64.exe", 111,
                      "ServerA", C.Role.MASTER.value)
    repo.add_terminal("slave1", "Slave1", "C:/x2/terminal64.exe", 222,
                      "ServerB", C.Role.SLAVE.value)
    mapper = SymbolMapper(repo)
    engine = CopyEngine(repo, mapper)
    sent = []
    send_fn = lambda tid, aid, atype, params: sent.append(
        (tid, aid, atype, params)) or True
    return repo, mapper, engine, sent, send_fn


def slave_runtime(repo, specs=None):
    return {
        "terminal_id": "slave1",
        "settings": repo.get_slave_settings("slave1"),
        "snapshot": {"login": 222, "balance": 5000.0, "equity": 5100.0,
                     "connected_to_broker": True,
                     "terminal_trade_allowed": True,
                     "positions": [], },
        "snapshot_age_ms": 100,
        "symbols": ["EURUSD", "EURUSD.m", "XAUUSD"],
        "specs_cache": specs or {"EURUSD": {"symbol": "EURUSD",
                                            "volume_min": 0.01,
                                            "volume_max": 100.0,
                                            "volume_step": 0.01,
                                            "spread_points": 10}},
        "open_positions_count": 0,
        "open_total_volume": 0.0,
    }


def open_event(volume=0.10, symbol="EURUSD", pos=5001, deal=9001):
    return {
        "type": C.EventType.POSITION_OPEN.value,
        "event_key": f"OPEN:{pos}:{deal}",
        "master_login": 111,
        "symbol": symbol,
        "position_id": pos,
        "order_id": 7001,
        "deal_id": deal,
        "side": "BUY",
        "volume": volume,
        "price": 1.10000,
        "sl": 1.09000,
        "tp": 1.12000,
        "detected_at_ms": 1,
        "payload": {},
    }


def test_open_flow_creates_mapping():
    repo, mapper, engine, sent, send_fn = setup_engine()
    ev = open_event()
    state = engine.plan_and_dispatch(ev, None, [slave_runtime(repo)],
                                     send_fn, "RUNNING")
    assert state == "QUEUED"
    assert len(sent) == 1
    tid, aid, atype, params = sent[0]
    assert atype == "open_position"
    assert params["symbol"] == "EURUSD"       # exact auto-map
    assert abs(params["volume"] - 0.10) < 1e-9  # multiplier 1.0
    assert params["sl"] == 1.09000 and params["tp"] == 1.12000

    # worker reports success
    engine.on_action_result(aid, True,
                            {"position_id": 8001, "order": 8001,
                             "volume": 0.10, "price": 1.10001},
                            "", 0, 10009, {}, 50000)
    mapping = repo.get_mapping(5001, "slave1")
    assert mapping is not None
    assert mapping["slave_position_id"] == 8001
    assert mapping["status"] == "OPEN"
    assert abs(mapping["deviation_percent"]) < 0.1


def test_duplicate_event_never_dispatches_twice():
    repo, mapper, engine, sent, send_fn = setup_engine()
    ev = open_event()
    engine.plan_and_dispatch(ev, None, [slave_runtime(repo)], send_fn, "RUNNING")
    n1 = len(sent)
    # same event_key again (e.g. snapshot replays) -> suppressed
    ev2 = open_event()
    ev2["id"] = "different-uuid"
    engine.plan_and_dispatch(ev2, None, [slave_runtime(repo)], send_fn, "RUNNING")
    assert len(sent) == n1, "duplicate event must not produce a second order"


def test_unmapped_symbol_blocked():
    repo, mapper, engine, sent, send_fn = setup_engine()
    rt = slave_runtime(repo)
    rt["symbols"] = ["GBPUSD"]  # no EURUSD at all
    ev = open_event()
    engine.plan_and_dispatch(ev, None, [rt], send_fn, "RUNNING")
    assert len(sent) == 0, "unmapped symbol must never be traded"
    actions = repo.list_actions_for_event(ev["id"])
    assert actions and actions[0]["state"] == "FAILED"
    assert "unmapped" in (actions[0]["error_message"] or "")


def test_pause_blocks_open_but_allows_close():
    repo, mapper, engine, sent, send_fn = setup_engine()
    ev = open_event()
    engine.plan_and_dispatch(ev, None, [slave_runtime(repo)], send_fn, "PAUSED")
    assert len(sent) == 0, "PAUSE must block new opens"

    # establish a mapping, then send a close while paused
    repo.insert_mapping(master_login=111, master_position_id=5001,
                        master_symbol="EURUSD", slave_terminal_id="slave1",
                        slave_position_id=8001, slave_symbol="EURUSD",
                        slave_volume_initial=0.10, slave_volume_current=0.10,
                        status="OPEN", created_at_ms=1)
    close_ev = {
        "type": C.EventType.POSITION_CLOSE_FULL.value,
        "event_key": "CLOSE:5001:9999",
        "master_login": 111, "symbol": "EURUSD", "position_id": 5001,
        "side": "BUY", "volume": 0.10, "volume_before": 0.10,
        "detected_at_ms": 2, "payload": {},
    }
    engine.plan_and_dispatch(close_ev, None, [slave_runtime(repo)],
                             send_fn, "PAUSED")
    closes = [s for s in sent if s[2] == "close_full"]
    assert len(closes) == 1, "PAUSE must still allow closing copied positions"


def test_partial_close_volume():
    repo, mapper, engine, sent, send_fn = setup_engine()
    repo.insert_mapping(master_login=111, master_position_id=5001,
                        master_symbol="EURUSD", slave_terminal_id="slave1",
                        slave_position_id=8001, slave_symbol="EURUSD",
                        slave_volume_initial=0.10, slave_volume_current=0.10,
                        status="OPEN", created_at_ms=1)
    ev = {
        "type": C.EventType.POSITION_CLOSE_PARTIAL.value,
        "event_key": "PART:5001:9005",
        "master_login": 111, "symbol": "EURUSD", "position_id": 5001,
        "side": "BUY", "volume": 0.04, "volume_before": 0.10,
        "detected_at_ms": 3, "payload": {},
    }
    engine.plan_and_dispatch(ev, None, [slave_runtime(repo)], send_fn, "RUNNING")
    partials = [s for s in sent if s[2] == "close_partial"]
    assert len(partials) == 1
    assert abs(partials[0][3]["volume"] - 0.04) < 1e-9  # 40% of 0.10


def test_volume_invalid_reported_not_sent():
    repo, mapper, engine, sent, send_fn = setup_engine()
    rt = slave_runtime(repo)
    rt["settings"]["lot_mode"] = "FIXED"
    rt["settings"]["fixed_lot"] = 0.005  # below broker min -> must block
    ev = open_event()
    engine.plan_and_dispatch(ev, None, [rt], send_fn, "RUNNING")
    assert len(sent) == 0
    actions = repo.list_actions_for_event(ev["id"])
    assert actions[0]["state"] == "FAILED"
    assert "volume" in (actions[0]["error_message"] or "")


def test_failed_result_no_retry_requires_reconciliation():
    repo, mapper, engine, sent, send_fn = setup_engine()
    ev = open_event()
    engine.plan_and_dispatch(ev, None, [slave_runtime(repo)], send_fn, "RUNNING")
    aid = sent[0][1]
    # timeout retcode -> RECONCILIATION_REQUIRED (never blind resend)
    state = engine.on_action_result(aid, False, {}, "TIMEOUT", 10012, 10012,
                                    {}, 300000)
    assert state == "RECONCILIATION_REQUIRED"
    # hard broker reject -> FAILED (final)
    ev2 = open_event(pos=5002, deal=9002)
    engine.plan_and_dispatch(ev2, None, [slave_runtime(repo)], send_fn, "RUNNING")
    aid2 = sent[-1][1]
    state2 = engine.on_action_result(aid2, False, {}, "NO_MONEY", 10019, 10019,
                                     {}, 300000)
    assert state2 == "FAILED"


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("copy engine integration tests: ALL PASS")
