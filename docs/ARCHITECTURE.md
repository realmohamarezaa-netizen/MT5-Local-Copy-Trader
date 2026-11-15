# Architecture

## Process & threading model

```
┌────────────────────────────────────────────────────────────────────┐
│ TradingCopier.exe (main process)                                   │
│                                                                    │
│  Qt UI thread ──(StateStore read @200ms)──> render                 │
│      │                                                             │
│  Engine thread: consumes IPC queue                                 │
│      │  - master snapshot -> MasterAnalyzer -> events              │
│      │  - CopyEngine: plan (symbol/volume/sltp/risk) -> dispatch   │
│      │  - action results -> mappings + state machine               │
│      │  - DB writes (single writer, SQLite WAL)                    │
│      │                                                             │
│  Watchdog thread: respawns crashed workers (3s period)             │
│  Reconciler thread: periodic master↔mapping↔slave verification     │
│  Listener thread per terminal: accepts pipe, drains JSON messages  │
└────────────┬───────────────┬───────────────┬───────────────────────┘
             │ Named Pipe    │ Named Pipe    │ Named Pipe
             ▼               ▼               ▼
       Worker proc 1    Worker proc 2    Worker proc N
       (terminal A)     (terminal B)     (terminal N)
       mt5.initialize(path=A) — independent MT5 API session each
```

- One **worker process per terminal** because the official MetaTrader5
  Python API allows exactly one terminal attach per process. Crashed
  workers never affect others; watchdog respawns them.
- **Named Pipes** (`multiprocessing.connection`, AF_PIPE on Windows, with
  shared authkey; current-user scope). JSON messages, length-framed.
- Engine thread is the single writer to SQLite (WAL). UI never blocks: it
  only reads a precomputed snapshot from `StateStore` on a QTimer.

## Event detection (master)

Per snapshot cycle (default 50ms):

1. `history_deals_get(now-window, now+60s)` — overlapping window (default
   10min). New deals (deduped by real deal ticket):
   - IN → POSITION_OPEN (or netting VOLUME_INCREASE if position known)
   - OUT/OUT_BY → POSITION_CLOSE_PARTIAL (remaining volume > 0) or
     POSITION_CLOSE_FULL
   - INOUT → CLOSE_FULL of old side + OPEN of remainder (netting reversal)
2. `positions_get()` diff — SL/TP modifications (`MOD:{pos}:{sl}:{tp}`),
   volume changes fallback, vanished positions (safety close).
3. `orders_get()` diff — pending PLACE/MODIFY/REMOVE; disappearance with an
   IN deal for that order ticket = FILL, not REMOVE.

Open+close inside one poll interval can never be missed (deals) and never
duplicated (deal-ticket dedup + DB unique `(master_login, event_key)`).

First snapshot after engine start is a **baseline** (no events) — this
implements "copy only new trades" default; explicit sync-existing is a
separate, user-confirmed path.

## Idempotency & order safety

- `events` table: UNIQUE(master_login, event_key); event_key derives from
  real MT5 tickets (e.g. `OPEN:{position_id}:{deal_id}`).
- `event_actions`: UNIQUE(event_id, terminal_id); states QUEUED→SENT→
  FILLED/VERIFIED/FAILED/RECONCILIATION_REQUIRED.
- Timeout / pipe loss mid-flight ⇒ RECONCILIATION_REQUIRED; **no blind
  resend**. Reconciler compares destination account state before anything.
- Broker rejects (NO_MONEY, MARKET_CLOSED, INVALID_STOPS, …) ⇒ FAILED final,
  surfaced in UI; INVALID_STOPS gets a single controlled retry only if the
  user enabled stop-level adjustment.
- Slave position verification after fill (`positions_get` by order ticket)
  before reporting success (FILL_UNVERIFIED otherwise).

## Volume / SLTP / mapping

- Volume: SAME/MULTIPLIER/FIXED/BALANCE_RATIO/EQUITY_RATIO, always rounded
  DOWN to destination symbol `volume_step`, clamped to `volume_max`,
  rejected below `volume_min` (never silently enlarged); partial-close
  closes full when the remainder would be untradeable.
- SL/TP: ABSOLUTE (default) or DISTANCE-from-entry per slave; worker-side
  sanity check rejects stops >50% away from price; order margin pre-check
  via `order_check` (optional).
- Symbol mapping: auto-verified only for exact names; heuristics stored as
  SUGGESTED but never auto-traded; manual mapping UI per slave.

## Storage

SQLite WAL at `%LOCALAPPDATA%\TradingCopier\data\copier.db`: terminals,
slave settings, symbol maps, events, event_actions, copy_mappings
(full master↔slave ticket mapping incl. volumes/prices/deviation), global
settings. Logs: JSON-lines with rotation (5MB × 10) under `logs\`.

## Packaging

- PyInstaller onedir (`build/pyinstaller/TradingCopier.spec`)
- Inno Setup per-user installer (`build/inno/TradingCopierSetup.iss`),
  no admin required, data dir untouched by uninstall
- GitHub Actions `build-windows.yml`: tests → PyInstaller → ISCC → ZIP →
  artifact + release on `v*` tags

## Latency budget (local parts)

Measured by `scripts/benchmark.py` (no broker):
- detect (snapshot diff + deals) median ≈0.2ms, p95 ≈0.4ms
- JSON snapshot serialize (30 positions) ≈0.08ms (~7KB)

End-to-end copy latency = detect + IPC dispatch (≤1ms) + worker execution
(mt5 call, typically 5–50ms) + broker RTT (broker-side, not ours). The app
records `latency_total_us` per action and shows rolling avg/p95 in the UI.
