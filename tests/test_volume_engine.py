"""Unit tests for the volume engine (no MT5, no orders - pure logic)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.engine.volume_engine import compute_open_volume, compute_partial_close_volume  # noqa: E402

SPECS = {"volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01}
SPECS_STEP_1 = {"volume_min": 1.0, "volume_max": 100.0, "volume_step": 1.0}
ACC = {"balance": 1000.0, "equity": 1200.0}


def test_multiplier():
    r = compute_open_volume("MULTIPLIER", 0.20, ACC, SPECS, lot_multiplier=0.5)
    assert r.ok and abs(r.volume - 0.10) < 1e-9, r


def test_same():
    r = compute_open_volume("SAME", 0.37, ACC, SPECS)
    assert r.ok and abs(r.volume - 0.37) < 1e-9, r


def test_fixed():
    r = compute_open_volume("FIXED", 0.5, ACC, SPECS, fixed_lot=0.05)
    assert r.ok and abs(r.volume - 0.05) < 1e-9, r


def test_balance_ratio():
    r = compute_open_volume("BALANCE_RATIO", 0.20, ACC, SPECS,
                            balance_ratio=1.0, master_balance=2000.0)
    assert r.ok and abs(r.volume - 0.10) < 1e-9, r


def test_equity_ratio():
    r = compute_open_volume("EQUITY_RATIO", 0.20, ACC, SPECS,
                            equity_ratio=1.0, master_equity=2400.0)
    assert r.ok and abs(r.volume - 0.10) < 1e-9, r


def test_below_min_rejected_not_enlarged():
    # 0.005 with multiplier 0.5 of 0.01 -> below min -> must FAIL
    r = compute_open_volume("MULTIPLIER", 0.01, ACC, SPECS, lot_multiplier=0.3)
    assert not r.ok, r


def test_rounds_down_to_step():
    r = compute_open_volume("MULTIPLIER", 0.11, ACC, SPECS, lot_multiplier=3)
    # 0.33 exactly on step
    assert r.ok and abs(r.volume - 0.33) < 1e-9, r
    r2 = compute_open_volume("MULTIPLIER", 0.105, ACC, SPECS, lot_multiplier=1)
    # 0.105 -> round down to 0.10
    assert r2.ok and abs(r2.volume - 0.10) < 1e-9, r2


def test_step_1_symbol():
    r = compute_open_volume("MULTIPLIER", 0.5, ACC, SPECS_STEP_1,
                            lot_multiplier=2)
    # 1.0 -> ok
    assert r.ok and abs(r.volume - 1.0) < 1e-9, r
    r2 = compute_open_volume("MULTIPLIER", 0.5, ACC, SPECS_STEP_1,
                             lot_multiplier=1)
    # 0.5 -> below min 1.0 -> rejected
    assert not r2.ok, r2


def test_max_lot_clamps_down():
    r = compute_open_volume("MULTIPLIER", 10.0, ACC, SPECS, lot_multiplier=100,
                            max_lot=2.0)
    assert r.ok and abs(r.volume - 2.0) < 1e-9, r


def test_partial_close_fraction():
    r = compute_partial_close_volume(0.5, 1.0, SPECS)
    assert r.ok and abs(r.volume - 0.50) < 1e-9, r


def test_partial_close_remainder_below_min_closes_full():
    # slave 0.10, closing 95% -> target 0.095 -> rounds down 0.09, remainder 0.01 ok
    r = compute_partial_close_volume(0.95, 0.10, SPECS)
    assert r.ok and abs(r.volume - 0.09) < 1e-9, r
    # slave 0.02, closing 50% -> target 0.01 ok, remainder 0.01 ok
    r2 = compute_partial_close_volume(0.5, 0.02, SPECS)
    assert r2.ok and abs(r2.volume - 0.01) < 1e-9, r2
    # slave 0.01, closing 50% -> target 0.005 below min -> SKIP (never enlarge),
    # the remaining 0.01 position is still valid
    r3 = compute_partial_close_volume(0.5, 0.01, SPECS)
    assert not r3.ok, r3
    # min>step symbol (e.g. vmin=0.10, step=0.01): slave 0.11, close 95% ->
    # target 0.1045 -> floor 0.10 (valid) but remainder 0.01 < min -> close full
    specs2 = {"volume_min": 0.10, "volume_max": 100.0, "volume_step": 0.01}
    r4 = compute_partial_close_volume(0.95, 0.11, specs2)
    assert r4.ok and abs(r4.volume - 0.11) < 1e-9, r4


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("volume engine tests: ALL PASS")
