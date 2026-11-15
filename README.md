# Trading Copier — Local Multi-Account MT5 Copy Trader (Windows x64)

A **fully local** MetaTrader 5 multi-account copy trading application for
Windows 10/11 x64. No cloud. No EA. No MQL5 files. No third-party copy
services. All processing, storage and UI run on your own machine.

- Connect to **unlimited** MT5 terminals installed on the same PC
- Pick one account as **MASTER**, any number as **SLAVE**
- Trades opened manually (or by any method) on the master are copied to all
  active slaves within milliseconds
- SL / TP modifications, partial closes, full closes, volume changes and
  pending-order lifecycle are all replicated
- Live dashboard: accounts, equity/margin, positions, copy activity, latency

## Architecture (summary)

| Layer | Technology |
|---|---|
| UI | Python 3.11 + PySide6 (Qt6), dark premium theme, FA/EN + RTL |
| MT5 access | Official `MetaTrader5` Python package (outside the terminal, no EA) |
| Isolation | One **worker process per terminal** (independent sessions, crash isolation) |
| IPC | Windows Named Pipes (`multiprocessing.connection`, JSON messages, authkey) |
| Engine | Event detection (positions diff + incremental history deals with overlap window), idempotent event queue, parallel slave dispatch, reconciliation |
| Storage | SQLite (WAL mode) in `%LOCALAPPDATA%\TradingCopier` |
| Secrets | Windows DPAPI (never plaintext) |
| Packaging | PyInstaller (onedir) + Inno Setup installer + GitHub Actions |

![flow](docs/architecture.png)

## Repository layout

```
app/
  core/         constants, models, utils
  database/     SQLite WAL schema + repository
  ipc/          named-pipe transport + JSON protocol
  workers/      per-terminal MT5 worker processes
  engine/       master analyzer, volume/symbol/risk engines, copy engine, reconciler
  ui/           PySide6 dashboard (main window, dialogs, theme, i18n)
  controller.py threading + engine state machine
  main_app.py   Qt bootstrap
main.py         entry point (freeze_support aware)
build/          PyInstaller spec, Inno Setup script, build_windows.bat
.github/        Windows CI: build EXE + Setup ZIP release
tests/          33 unit/integration tests (mocked - never place real orders)
scripts/        validate_connection.py (Phase-1 check), benchmark.py
docs/           installation / MT5 setup / troubleshooting (Persian) + architecture
```

## Getting the Windows installer

The installer is built automatically by GitHub Actions on every `v*` tag:

1. Go to **Releases** in this repository
2. Download **`TradingCopierSetup_x64.zip`** (contains the classic
   `TradingCopierSetup_x64.exe` installer)
3. Unzip, run the installer, done. Per-user install (no admin required),
   desktop + start-menu shortcuts, full uninstaller included.

To build locally on Windows: install Python 3.11 x64 and
[Inno Setup 6](https://jrsoftware.org/isinfo.php), then run
`build\build_windows.bat`.

## First run checklist (demo accounts!)

1. Enable **Algo Trading** in each MT5 terminal (toolbar button).
2. Run the app → **Add Terminal** → scan or browse to `terminal64.exe`.
3. Make sure each terminal is logged in (the app uses the terminal's own
   session; password field is optional, stored only via DPAPI).
4. Right-click a terminal row → **Set as Master**. Others → remain slaves.
5. Configure each slave (lot mode, risk caps, symbol mapping) via
   **Settings**.
6. Press **START COPYING**. Answer "No" to the sync question to copy only
   new trades (recommended default).
7. Test on **demo accounts** first. Real accounts are your decision.

Detailed Persian guides: [docs/INSTALL-fa.md](docs/INSTALL-fa.md),
[docs/MT5-SETUP-fa.md](docs/MT5-SETUP-fa.md),
[docs/TROUBLESHOOTING-fa.md](docs/TROUBLESHOOTING-fa.md).

## Tests

```bash
pip install pytest
pytest tests -q        # 33 tests, all mocked; never touches real MT5
```

Latency benchmark of the local pipeline:

```bash
python scripts/benchmark.py
```

Measured on the CI/dev machine (no broker involved): master snapshot event
detection median **≈0.2 ms**, p95 **≈0.4 ms**; 30-position JSON snapshot
serialization ≈0.08 ms / ~7 KB. End-to-end copy latency is dominated by the
broker round-trip and is measured at runtime via
`event_actions.latency_total_us`.

## Safety principles implemented

- Every event is processed **exactly once** (DB-unique event keys from real
  deal/order/position tickets)
- Timeout/unknown outcome ⇒ `RECONCILIATION_REQUIRED`, **never** a blind resend
- Manual trades on slaves are never touched (mapping-scoped operations only)
- Unknown account state ⇒ no new orders (fail-safe)
- Master closed ⇒ slaves closed (also enforced by periodic reconciliation)
- PAUSE blocks new exposure but keeps managing copied positions
- EMERGENCY STOP halts dispatch instantly and reports in-flight actions
- CLOSE COPIED POSITIONS closes only mapping-owned positions, with confirmation

## Honest limitations

- Verified in this repository: 33 automated tests (event detection, dedup,
  volume math, symbol mapping, copy flow, IPC roundtrip), Windows CI builds
  the EXE/Setup. **Live multi-terminal verification must be done on a real
  Windows machine with MT5 demo terminals** — use
  `scripts/validate_connection.py` per terminal (Phase-1 checklist in docs).
- Netting-master → hedging-slave copying is allowed but partial-close
  semantics differ; read docs before mixing account types.
- Same `terminal64.exe` used for two data folders (`/portable`) cannot be
  attached twice from one app instance (MT5 API limitation: one connection
  per process per install path).
