"""MT5 worker process entry (spawn target for multiprocessing)."""
from __future__ import annotations

import logging

from app.workers.mt5_worker import WorkerConfig, run_worker

log = logging.getLogger("worker.entry")


def worker_process_entry(config_dict: dict, pipe_address: str):
    """Runs inside a dedicated process per terminal.

    config_dict keys: terminal_id, terminal_path, login, password(optional),
    server, role, poll_ms_master, poll_ms_slave, deal_window_sec, is_master.
    """
    try:
        cfg = WorkerConfig.from_dict(config_dict)
        run_worker(cfg, pipe_address)
    except Exception:
        log.exception("worker crashed for terminal %s", config_dict.get("terminal_id"))
