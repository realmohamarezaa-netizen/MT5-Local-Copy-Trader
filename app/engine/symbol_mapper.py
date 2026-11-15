"""Symbol mapping engine.

Safety policy: auto-mapping is allowed ONLY for exact symbol-name matches
found in the destination account's symbol list. Heuristic matches are saved
with status SUGGESTED and NEVER auto-traded - user must confirm manually
in the mapping UI. Ambiguity = no trade (fail safe).
"""
from __future__ import annotations

import logging
from typing import Optional

from app.core import constants as C
from app.core.utils import symbol_base

log = logging.getLogger("engine.mapper")


class SymbolMapper:
    def __init__(self, repo):
        self.repo = repo

    def resolve(self, slave_terminal_id: str, master_symbol: str,
                slave_symbols: list[str]) -> tuple[Optional[str], str]:
        """Returns (slave_symbol|None, status)."""
        master_symbol = (master_symbol or "").strip()
        if not master_symbol:
            return None, C.SymbolMapStatus.UNMAPPED.value

        row = self.repo.get_symbol_map(slave_terminal_id, master_symbol)
        if row is not None and row["status"] == C.SymbolMapStatus.VERIFIED.value:
            return row["slave_symbol"], C.SymbolMapStatus.VERIFIED.value

        # exact match -> auto-verified
        exact = next((s for s in slave_symbols if s == master_symbol), None)
        if exact is not None:
            self.repo.upsert_symbol_map(slave_terminal_id, master_symbol, exact,
                                        C.SymbolMapStatus.VERIFIED.value,
                                        "auto: exact name match")
            return exact, C.SymbolMapStatus.VERIFIED.value

        # heuristic: same base, save as SUGGESTED only
        base = symbol_base(master_symbol)
        candidates = [s for s in slave_symbols
                      if symbol_base(s) == base and s != master_symbol]
        suggestion = candidates[0] if len(candidates) == 1 else None
        if row is None or row["status"] == C.SymbolMapStatus.UNMAPPED.value:
            self.repo.upsert_symbol_map(
                slave_terminal_id, master_symbol, suggestion,
                C.SymbolMapStatus.SUGGESTED.value,
                f"auto suggestion of {','.join(candidates[:5])}" if candidates
                else "no candidate found")
        return None, C.SymbolMapStatus.UNMAPPED.value

    def set_manual(self, slave_terminal_id: str, master_symbol: str,
                   slave_symbol: Optional[str], verified: bool = True) -> None:
        status = (C.SymbolMapStatus.VERIFIED.value if verified
                  else C.SymbolMapStatus.UNMAPPED.value)
        note = "manual"
        if slave_symbol:
            if not verified:
                note = "manual (unverified)"
            else:
                note = f"manual: {master_symbol} -> {slave_symbol}"
        self.repo.upsert_symbol_map(slave_terminal_id, master_symbol,
                                    slave_symbol, status, note)
