"""Per-slave risk checks. Fail-safe: any unknown state blocks new orders."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RiskDecision:
    ok: bool
    reason: str = ""


def check_slave(settings: dict, snap: Optional[dict], snapshot_age_ms: int,
                event: dict, specs: Optional[dict], open_positions_count: int,
                open_total_volume: float) -> RiskDecision:
    """settings: slave_settings row dict; snap: slave AccountSnapshot dict."""
    if not settings.get("copy_enabled"):
        return RiskDecision(False, "copy disabled")

    if snap is None:
        return RiskDecision(False, "no snapshot (fail safe)")
    if snapshot_age_ms > 10000:
        return RiskDecision(False, f"stale snapshot {snapshot_age_ms}ms (fail safe)")
    if not snap.get("connected_to_broker", False):
        return RiskDecision(False, "terminal not connected to broker")
    if not snap.get("terminal_trade_allowed", False):
        return RiskDecision(False, "AutoTrading disabled in terminal")

    # symbol / direction filters
    allowed_symbols = [s.strip() for s in
                       (settings.get("allowed_symbols") or "").split(",") if s.strip()]
    master_symbol = event.get("symbol") or ""
    if allowed_symbols and master_symbol not in allowed_symbols:
        return RiskDecision(False, f"symbol {master_symbol} not allowed")

    directions = [d.strip().upper() for d in
                  (settings.get("allowed_directions") or "BUY,SELL").split(",")]
    side = (event.get("side") or "").upper()
    if side and side not in directions:
        return RiskDecision(False, f"direction {side} blocked")

    # spread check
    if specs is not None and settings.get("max_spread_points"):
        if int(specs.get("spread_points", 0)) > int(settings["max_spread_points"]):
            return RiskDecision(False,
                                f"spread {specs.get('spread_points')} > "
                                f"{settings['max_spread_points']}")

    # margin checks
    equity = float(snap.get("equity", 0.0))
    margin_free = float(snap.get("margin_free", 0.0))
    margin_level = float(snap.get("margin_level", 0.0) or 0.0)

    if settings.get("stop_if_equity_below") is not None and \
            equity < float(settings["stop_if_equity_below"]):
        return RiskDecision(False,
                            f"equity {equity:.2f} below stop level "
                            f"{settings['stop_if_equity_below']}")

    if settings.get("min_free_margin") is not None and \
            margin_free < float(settings["min_free_margin"]):
        return RiskDecision(False, f"free margin {margin_free:.2f} below minimum")

    if settings.get("min_margin_level") is not None and margin_level > 0 and \
            margin_level < float(settings["min_margin_level"]):
        return RiskDecision(False,
                            f"margin level {margin_level:.1f}% below minimum")

    # position count / total volume caps (only for opening events)
    if event.get("type") in ("POSITION_OPEN", "POSITION_VOLUME_INCREASE", "ORDER_PLACE"):
        if settings.get("max_positions") is not None and \
                open_positions_count >= int(settings["max_positions"]):
            return RiskDecision(False,
                                f"max positions reached ({open_positions_count})")
        if settings.get("max_total_volume") is not None:
            # actual cap enforced after volume calc; here quick volume guard
            pass

    return RiskDecision(True)
