"""Unit tests for master event detection (no MT5, pure snapshots)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.engine.master_analyzer import MasterAnalyzer  # noqa: E402


def snap(positions=(), orders=(), deals=(), login=111):
    return {
        "login": login,
        "positions": list(positions),
        "orders": list(orders),
        "deals": list(deals),
        "ts_utc_ms": 0,
    }


def pos(ticket, symbol="EURUSD", ptype=0, volume=0.10, sl=0.0, tp=0.0,
        price_open=1.10000):
    return {"ticket": ticket, "symbol": symbol, "type": ptype, "volume": volume,
            "price_open": price_open, "sl": sl, "tp": tp,
            "price_current": price_open + 0.001, "profit": 1.5, "swap": 0.0,
            "time_msc": 1, "magic": 0, "comment": ""}


def deal(ticket, position_id, order, entry, volume, ptype=0, symbol="EURUSD",
         price=1.10, profit=0.0, time_msc=1):
    return {"ticket": ticket, "order": order, "position_id": position_id,
            "symbol": symbol, "type": ptype, "entry": entry, "volume": volume,
            "price": price, "profit": profit, "commission": 0.0, "swap": 0.0,
            "time_msc": time_msc, "comment": ""}


def order(ticket, symbol="EURUSD", otype=2, volume=0.1, price=1.09, sl=0, tp=0,
          state=1):
    return {"ticket": ticket, "symbol": symbol, "type": otype,
            "volume_initial": volume, "volume_current": volume,
            "price_open": price, "sl": sl, "tp": tp, "state": state,
            "time_setup_msc": 1, "magic": 0, "comment": "", "position_id": 0}


def test_open_detected_from_deal():
    a = MasterAnalyzer(111)
    events = a.analyze(snap())
    assert events == []
    events = a.analyze(snap(
        positions=[pos(5001)],
        deals=[deal(9001, 5001, 7001, entry=0, volume=0.10)],
    ))
    opens = [e for e in events if e["type"] == "POSITION_OPEN"]
    assert len(opens) == 1 and opens[0]["position_id"] == 5001
    assert opens[0]["side"] == "BUY" and abs(opens[0]["volume"] - 0.10) < 1e-9
    # second identical snapshot: no duplicate
    events2 = a.analyze(snap(
        positions=[pos(5001)],
        deals=[deal(9001, 5001, 7001, entry=0, volume=0.10)],
    ))
    assert not [e for e in events2 if e["type"] == "POSITION_OPEN"]


def test_open_then_close_within_one_poll():
    a = MasterAnalyzer(111)
    a.analyze(snap())
    events = a.analyze(snap(
        positions=[],  # already closed
        deals=[
            deal(9001, 5001, 7001, entry=0, volume=0.10, time_msc=1),
            deal(9002, 5001, 7002, entry=1, volume=0.10, profit=2.0, time_msc=2),
        ],
    ))
    types = [e["type"] for e in events]
    assert "POSITION_OPEN" in types and "POSITION_CLOSE_FULL" in types
    closes = [e for e in events if e["type"] == "POSITION_CLOSE_FULL"]
    assert abs(closes[0]["profit"] - 2.0) < 1e-9


def test_partial_close():
    a = MasterAnalyzer(111)
    a.analyze(snap())
    a.analyze(snap(positions=[pos(5001)],
                   deals=[deal(9001, 5001, 7001, entry=0, volume=0.10)]))
    events = a.analyze(snap(positions=[pos(5001, volume=0.06)],
                            deals=[deal(9003, 5001, 7003, entry=1, volume=0.04)]))
    partials = [e for e in events if e["type"] == "POSITION_CLOSE_PARTIAL"]
    assert len(partials) == 1
    assert abs(partials[0]["volume"] - 0.04) < 1e-9
    assert abs(partials[0]["volume_before"] - 0.10) < 1e-9


def test_sltp_modify():
    a = MasterAnalyzer(111)
    a.analyze(snap())
    a.analyze(snap(positions=[pos(5001, sl=1.09)],
                   deals=[deal(9001, 5001, 7001, entry=0, volume=0.10)]))
    events = a.analyze(snap(positions=[pos(5001, sl=1.08, tp=1.12)],
                            deals=[]))
    mods = [e for e in events if e["type"] == "POSITION_MODIFY_SLTP"]
    assert len(mods) == 1
    assert mods[0]["sl"] == 1.08 and mods[0]["tp"] == 1.12
    # no duplicate when unchanged
    events2 = a.analyze(snap(positions=[pos(5001, sl=1.08, tp=1.12)], deals=[]))
    assert not [e for e in events2 if e["type"] == "POSITION_MODIFY_SLTP"]


def test_pending_place_modify_remove():
    a = MasterAnalyzer(111)
    a.analyze(snap())
    events = a.analyze(snap(orders=[order(8001)]))
    places = [e for e in events if e["type"] == "ORDER_PLACE"]
    assert len(places) == 1 and places[0]["order_id"] == 8001
    assert places[0]["payload"]["order_type"] == 2  # BUY_LIMIT

    events = a.analyze(snap(orders=[order(8001, price=1.085)]))
    mods = [e for e in events if e["type"] == "ORDER_MODIFY"]
    assert len(mods) == 1

    # removed without fill
    events = a.analyze(snap(orders=[]))
    removes = [e for e in events if e["type"] == "ORDER_REMOVE"]
    assert len(removes) == 1 and removes[0]["order_id"] == 8001


def test_pending_filled_not_removed():
    a = MasterAnalyzer(111)
    a.analyze(snap())
    a.analyze(snap(orders=[order(8001)]))
    # order vanished but an IN deal for that order appeared -> fill, not remove
    events = a.analyze(snap(
        positions=[pos(5002)],
        deals=[deal(9010, 5002, 8001, entry=0, volume=0.10)],
        orders=[]))
    types = [e["type"] for e in events]
    assert "ORDER_REMOVE" not in types
    assert "POSITION_OPEN" in types


def test_manual_slave_trade_not_flagged():
    """Analyzer only ever sees the MASTER snapshot; this test asserts that a
    position present from the very first snapshot is treated as pre-existing:
    the analyzer does NOT emit open events for it (startup state)."""
    a = MasterAnalyzer(111)
    events = a.analyze(snap(positions=[pos(4444)]))
    assert not [e for e in events if e["type"] == "POSITION_OPEN"]


def test_selloff_full_close_removes_state():
    a = MasterAnalyzer(111)
    a.analyze(snap())
    a.analyze(snap(positions=[pos(5001, ptype=1)],
                   deals=[deal(9001, 5001, 7001, entry=0, volume=0.10, ptype=1)]))
    events = a.analyze(snap(positions=[],
                            deals=[deal(9002, 5001, 7002, entry=1, volume=0.10,
                                        ptype=1, profit=-1.5)]))
    closes = [e for e in events if e["type"] == "POSITION_CLOSE_FULL"]
    assert len(closes) == 1
    # close event again with same state -> nothing (state removed)
    events2 = a.analyze(snap(positions=[], deals=[]))
    assert not [e for e in events2 if e["type"] == "POSITION_CLOSE_FULL"]


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("master analyzer tests: ALL PASS")
