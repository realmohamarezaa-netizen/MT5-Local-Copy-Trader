"""Periodic reconciliation: master positions vs copy_mappings vs slave
positions. Safety net for missed events, reconnects, manual closes.

Policy:
- mapping OPEN but master position gone  -> close slave copy (safety-first)
- mapping OPEN but slave position gone   -> mark RECONCILE (manual close?
  never reopen on our own)
- volume drift beyond epsilon            -> mark RECONCILE + report
- master position exists, no mapping, opened AFTER engine start, engine
  running -> missed copy candidate -> only flagged (auto-copy requires
  explicit sync mode at START)
"""
from __future__ import annotations

import logging

from app.core import constants as C
from app.core.utils import now_ms

log = logging.getLogger("engine.reconciler")


class Reconciler:
    def __init__(self, repo, send_fn):
        self.repo = repo
        self.send_fn = send_fn

    def run(self, master_login: int, master_positions: dict,
            slave_runtimes: dict) -> list[str]:
        """master_positions: {position_id: {volume, symbol, ...}}
        slave_runtimes: {terminal_id: {snapshot: dict|None, ...}}
        Returns list of human-readable findings (also shown in UI)."""
        findings: list[str] = []
        now = now_ms()
        mappings = self.repo.list_open_mappings()
        for m in mappings:
            mapping = dict(m)
            tid = mapping["slave_terminal_id"]
            rt = slave_runtimes.get(tid)
            master_pos = master_positions.get(mapping["master_position_id"])

            # 1) master closed but mapping still open -> close slave copy
            if master_pos is None and \
                    mapping["status"] in (C.MappingStatus.OPEN.value,
                                          C.MappingStatus.PARTIAL.value):
                if mapping.get("slave_position_id") and rt is not None:
                    import uuid
                    action_id = uuid.uuid4().hex
                    ev_id = self.repo.insert_synthetic_event(
                        "RECONCILE_CLOSE",
                        f"master pos {mapping['master_position_id']} closed")
                    self.repo.insert_action(
                        action_id, ev_id, tid,
                        {"slave_position_id": mapping["slave_position_id"],
                         "_reconcile": True})
                    sent = self.send_fn(tid, action_id, "close_full",
                                        {"slave_position_id":
                                         mapping["slave_position_id"]})
                    if sent:
                        self.repo.update_action(
                            action_id, state=C.ActionState.SENT.value,
                            sent_at_ms=now)
                        self.repo.update_mapping(
                            mapping["id"], status=C.MappingStatus.CLOSED.value)
                        findings.append(
                            f"RECONCILE: master pos {mapping['master_position_id']} "
                            f"closed -> closed copy on {tid}")
                else:
                    self.repo.update_mapping(
                        mapping["id"], status=C.MappingStatus.RECONCILE.value,
                        error_message="master closed; no slave link")
                    findings.append(
                        f"RECONCILE: mapping {mapping['id']} needs review "
                        "(master closed, slave unknown)")
                continue

            # 2) slave snapshot available: verify slave position exists
            if rt is not None and rt.get("snapshot"):
                slave_positions = {int(p["ticket"]): p
                                   for p in rt["snapshot"].get("positions", [])}
                spid = mapping.get("slave_position_id")
                if spid and spid not in slave_positions:
                    self.repo.update_mapping(
                        mapping["id"], status=C.MappingStatus.RECONCILE.value,
                        error_message="slave position missing (closed manually?)")
                    findings.append(
                        f"RECONCILE: slave position {spid} missing on {tid}")
                elif spid and spid in slave_positions:
                    drift = abs(float(slave_positions[spid]["volume"]) -
                                float(mapping.get("slave_volume_current") or 0.0))
                    if drift > C.VOLUME_EPS:
                        self.repo.update_mapping(
                            mapping["id"],
                            slave_volume_current=float(
                                slave_positions[spid]["volume"]),
                            error_message=f"volume drift corrected ({drift})")
                        findings.append(
                            f"RECONCILE: volume drift {drift} on {tid} corrected")
        return findings
