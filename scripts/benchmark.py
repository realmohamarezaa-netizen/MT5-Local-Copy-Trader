"""Benchmarks the local pipeline (no MT5 required):
- snapshot analysis latency (detect -> events)
- JSON snapshot serialization size/time
Run: python scripts/benchmark.py
"""
from __future__ import annotations

import json
import random
import statistics
import sys
import time

sys.path.insert(0, ".")

from app.engine.master_analyzer import MasterAnalyzer  # noqa: E402


def make_snapshot(n_positions: int, n_deals: int, login=111):
    positions = []
    deals = []
    for i in range(n_positions):
        positions.append({
            "ticket": 100000 + i, "symbol": random.choice(
                ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY"]),
            "type": random.randint(0, 1), "volume": 0.1,
            "price_open": 1.1 + random.random() * 0.01,
            "sl": 0.0, "tp": 0.0, "price_current": 1.105,
            "profit": random.uniform(-50, 50), "swap": 0.0,
            "time_msc": 1, "magic": 0, "comment": "",
        })
    for i in range(n_deals):
        deals.append({
            "ticket": 900000 + i, "order": 800000 + i,
            "position_id": 100000 + (i % n_positions),
            "symbol": "EURUSD", "type": random.randint(0, 1),
            "entry": 0, "volume": 0.1, "price": 1.1, "profit": 0.0,
            "commission": 0.0, "swap": 0.0, "time_msc": i + 1, "comment": "",
        })
    return {"login": login, "positions": positions, "orders": [],
            "deals": deals, "ts_utc_ms": 0}


def bench_analyzer(cycles: int = 200, n_positions: int = 30) -> dict:
    a = MasterAnalyzer(111)
    a.analyze(make_snapshot(n_positions, n_positions))
    lat_detect = []
    for c in range(cycles):
        snap = make_snapshot(n_positions + c, 0)
        # add a fresh deal to force detection work
        snap["deals"] = [{
            "ticket": 990000 + c, "order": 890000 + c,
            "position_id": 100000 + n_positions + c, "symbol": "EURUSD",
            "type": 0, "entry": 0, "volume": 0.1, "price": 1.1, "profit": 0.0,
            "commission": 0.0, "swap": 0.0, "time_msc": 5, "comment": "",
        }]
        t0 = time.perf_counter()
        a.analyze(snap)
        lat_detect.append((time.perf_counter() - t0) * 1000)
    return {
        "detect_median_ms": statistics.median(lat_detect),
        "detect_p95_ms": sorted(lat_detect)[int(len(lat_detect) * 0.95) - 1],
    }


def bench_snapshot_json(n_positions: int = 30) -> dict:
    snap = make_snapshot(n_positions, 0)
    t0 = time.perf_counter()
    for _ in range(500):
        raw = json.dumps(snap)
    ms = (time.perf_counter() - t0) / 500 * 1000
    return {"serialize_ms": round(ms, 3), "payload_bytes": len(raw.encode())}


if __name__ == "__main__":
    print("== Local pipeline benchmark (no broker involved) ==")
    for n in (10, 30, 100):
        r = bench_analyzer(200, n)
        print(f"positions={n}: detect median {r['detect_median_ms']:.3f}ms, "
              f"p95 {r['detect_p95_ms']:.3f}ms")
    r = bench_snapshot_json(30)
    print(f"snapshot JSON (30 pos): {r['serialize_ms']}ms, "
          f"{r['payload_bytes']} bytes")
    print("NOTE: broker-side execution latency is NOT included by definition; "
          "measure end-to-end copy latency on your own accounts using the "
          "activity feed timestamps and event_actions.latency_total_us.")
