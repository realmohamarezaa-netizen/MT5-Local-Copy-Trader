"""Headless smoke test of the controller wiring (works on any OS).

Spawns the real controller with two fake terminals; on Linux the MT5 import
fails inside workers (expected) and the controller must still handle hellos,
publish state and stay alive. On Windows with real terminals this exercises
the full path.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.controller import AppController  # noqa: E402


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="tc-smoke-")
    print(f"data dir: {tmp}")
    ctrl = AppController(data_dir=tmp)
    ctrl.initialize()

    tid1 = ctrl.add_terminal("Master-Demo", "C:/fake/terminal64.exe")
    tid2 = ctrl.add_terminal("Slave-Demo", "C:/fake2/terminal64.exe")
    ctrl.set_slave(tid2)

    # let workers spawn and say hello (Linux: MT5 import fails -> hello ok=False)
    time.sleep(6)
    state = ctrl.store.get()
    assert state["stats"]["accounts_total"] == 2, state["stats"]
    slaves = state["slaves"]
    assert len(slaves) == 1 and slaves[0]["terminal_id"] == tid2

    # engine controls: start requires a master
    ctrl.unassign(tid1)   # temporarily unset the master
    try:
        ctrl.start_copying()
        raise AssertionError("start_copying without master must fail")
    except ValueError:
        pass
    ctrl.set_master(tid1)
    ctrl.set_slave(tid2)
    ctrl.pause_copying()
    ctrl.resume_copying()
    ctrl.stop_copying()
    ctrl.emergency_stop()

    # settings persistence
    ctrl.update_slave_settings(tid2, lot_mode="FIXED", fixed_lot=0.02)
    s = ctrl.repo.get_slave_settings(tid2)
    assert s["lot_mode"] == "FIXED" and abs(s["fixed_lot"] - 0.02) < 1e-9

    # global settings + language
    ctrl.set_global_setting("language", "fa")
    assert ctrl.repo.get_setting("language") == "fa"

    # positions view (empty) does not crash
    assert ctrl.get_positions_view() == []

    act = ctrl.store.get_activity()
    print(f"activity entries: {len(act)}; sample: {act[:2]}")
    print("engine state:", ctrl.engine_state)
    print("terminals:", [(t["terminal_id"][:8], t["name"])
                         for t in [state["master"] or {}] + state["slaves"]
                         if t])

    ctrl.delete_terminal(tid1)
    ctrl.delete_terminal(tid2)
    time.sleep(1)
    ctrl.shutdown()
    print("SMOKE TEST OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
