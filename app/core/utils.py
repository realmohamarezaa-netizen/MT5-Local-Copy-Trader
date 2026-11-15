"""Small shared helpers."""
from __future__ import annotations

import time
from typing import Iterable, Optional, Tuple


def now_ms() -> int:
    """Wall-clock UTC milliseconds."""
    return int(time.time() * 1000)


def monotonic_ns() -> int:
    return time.perf_counter_ns()


def round_to_step(value: float, step: float) -> float:
    """Round DOWN to the nearest multiple of step (never round up volume)."""
    if step <= 0:
        return value
    steps = int((value + 1e-9) / step)
    result = round(steps * step, 8)
    return result


def normalize_volume(volume: float, vmin: float, vmax: float, step: float) -> Tuple[Optional[float], str]:
    """Normalize a requested volume to broker constraints.

    Returns (volume, "") on success or (None, reason) when invalid.
    Rounding is always DOWN to the symbol step; if the result falls below
    volume_min the request is rejected (never silently enlarged).
    """
    if volume <= 0:
        return None, "volume<=0"
    vol = round_to_step(volume, step if step > 0 else 0.01)
    if vol < vmin - 1e-9:
        return None, f"below_min:{vol:.8f}<{vmin}"
    if vmax > 0 and vol > vmax + 1e-9:
        vol = vmax  # clamp to broker max (still a valid volume)
    return vol, ""


def format_float(v: float, digits: int = 2) -> str:
    return f"{v:.{digits}f}"


def symbol_base(symbol: str) -> str:
    """Strip broker suffixes: EURUSD.a / EURUSDm / EURUSD.pro -> EURUSD."""
    s = symbol.upper()
    for sep in (".", "-", "_"):
        if sep in s:
            s = s.split(sep)[0]
            break
    return s


def first(iterable: Iterable):
    for x in iterable:
        return x
    return None
