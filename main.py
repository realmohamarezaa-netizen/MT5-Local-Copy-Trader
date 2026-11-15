"""Trading Copier - entry point.

IMPORTANT: multiprocessing.freeze_support() must be the first call when
running as a frozen PyInstaller executable, because MT5 workers are spawned
child processes.
"""
import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()

    # Qt / UI imports only after freeze_support (child processes never reach here
    # thanks to freeze_support intercepting spawn bootstrap).
    from app.controller import AppController
    from app.main_app import run_app

    controller = AppController()
    controller.initialize()
    return run_app(controller)


if __name__ == "__main__":
    sys.exit(main())
