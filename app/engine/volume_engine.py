"""Volume calculation engine for slave accounts.

Modes: SAME / MULTIPLIER / FIXED / BALANCE_RATIO / EQUITY_RATIO.
Always normalized against the DESTINATION symbol specs:
round DOWN to volume_step, clamp to volume_max, reject below volume_min
(no unsafe silent enlargement).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core import constants as C
from app.core.utils import normalize_volume


@dataclass
class VolumeResult:
    ok: bool
    volume: Optional[float] = None
    reason: str = ""


def compute_open_volume(
    lot_mode: str,
    master_volume: float,
    slave_account: dict,          # snapshot dict (balance/equity)
    specs: dict,                  # SymbolSpecs dict of DEST symbol
    lot_multiplier: float = 1.0,
    fixed_lot: float = 0.0,
    balance_ratio: float = 1.0,
    equity_ratio: float = 1.0,
    max_lot: float = None,
    master_balance: float = 0.0,
    master_equity: float = 0.0,
) -> VolumeResult:
    vmin = float(specs.get("volume_min", 0.01) or 0.01)
    vmax = float(specs.get("volume_max", 0.0) or 0.0)
    step = float(specs.get("volume_step", 0.01) or 0.01)

    if lot_mode == C.LotMode.SAME.value:
        raw = master_volume
    elif lot_mode == C.LotMode.MULTIPLIER.value:
        raw = master_volume * float(lot_multiplier)
    elif lot_mode == C.LotMode.FIXED.value:
        raw = float(fixed_lot)
    elif lot_mode == C.LotMode.BALANCE_RATIO.value:
        if master_balance <= 0:
            return VolumeResult(False, reason="master balance unknown")
        raw = master_volume * (float(slave_account.get("balance", 0.0)) /
                               master_balance) * float(balance_ratio)
    elif lot_mode == C.LotMode.EQUITY_RATIO.value:
        if master_equity <= 0:
            return VolumeResult(False, reason="master equity unknown")
        raw = master_volume * (float(slave_account.get("equity", 0.0)) /
                               master_equity) * float(equity_ratio)
    else:
        return VolumeResult(False, reason=f"unknown lot mode {lot_mode}")

    vol, err = normalize_volume(raw, vmin, vmax, step)
    if vol is None:
        return VolumeResult(False, reason=f"volume {raw:.4f} invalid for symbol: {err}")

    if max_lot is not None and max_lot > 0 and vol > max_lot:
        # risk cap: clamp DOWN to user max (still >= vmin since vol >= vmin)
        clamped, err2 = normalize_volume(float(max_lot), vmin, vmax, step)
        if clamped is None:
            return VolumeResult(False, reason=f"max_lot {max_lot} below symbol min")
        vol = clamped
    return VolumeResult(True, volume=vol)


def compute_partial_close_volume(
    closed_fraction: float,
    slave_current_volume: float,
    specs: dict,
) -> VolumeResult:
    """Partial close: fraction of master volume -> absolute slave volume.
    - target below volume_min but remaining volume is also below min -> close full
    - target below volume_min but remainder fine -> skip with reason (no unsafe op)
    """
    vmin = float(specs.get("volume_min", 0.01) or 0.01)
    vmax = float(specs.get("volume_max", 0.0) or 0.0)
    step = float(specs.get("volume_step", 0.01) or 0.01)

    frac = max(0.0, min(1.0, closed_fraction))
    target = slave_current_volume * frac
    vol, err = normalize_volume(target, vmin, vmax, step)
    if vol is None or vol < vmin - C.VOLUME_EPS:
        remainder = slave_current_volume - (vol or 0.0)
        if remainder < vmin - C.VOLUME_EPS:
            # remainder would be untradeable -> close the whole position
            return VolumeResult(True, volume=slave_current_volume,
                                reason="closed_full_because_remainder_below_min")
        return VolumeResult(False,
                            reason=f"partial volume {target:.4f} below min {vmin}")
    if slave_current_volume - vol < vmin - C.VOLUME_EPS:
        # after partial close the remainder would be below min -> close full
        return VolumeResult(True, volume=slave_current_volume,
                            reason="closed_full_because_remainder_below_min")
    return VolumeResult(True, volume=vol)
