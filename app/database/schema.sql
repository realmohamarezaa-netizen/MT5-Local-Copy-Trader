-- Trading Copier SQLite schema (WAL mode enabled in code)

CREATE TABLE IF NOT EXISTS terminals (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    terminal_path     TEXT NOT NULL,
    login             INTEGER,
    server            TEXT,
    role              TEXT NOT NULL DEFAULT 'UNASSIGNED',
    enabled           INTEGER NOT NULL DEFAULT 1,
    blocked           INTEGER NOT NULL DEFAULT 0,
    enc_password      BLOB,
    account_currency  TEXT,
    account_name      TEXT,
    leverage          INTEGER,
    margin_mode       TEXT,
    mt5_version       TEXT,
    trade_allowed     INTEGER,
    algo_allowed      INTEGER,
    last_connected_at TEXT,
    last_error        TEXT,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS slave_settings (
    terminal_id        TEXT PRIMARY KEY REFERENCES terminals(id) ON DELETE CASCADE,
    copy_enabled       INTEGER NOT NULL DEFAULT 1,
    lot_mode           TEXT    NOT NULL DEFAULT 'MULTIPLIER',
    lot_multiplier     REAL    NOT NULL DEFAULT 1.0,
    fixed_lot          REAL    NOT NULL DEFAULT 0.01,
    balance_ratio      REAL    NOT NULL DEFAULT 1.0,
    equity_ratio       REAL    NOT NULL DEFAULT 1.0,
    max_lot            REAL,
    max_positions      INTEGER,
    max_total_volume   REAL,
    max_slippage_points INTEGER NOT NULL DEFAULT 50,
    max_spread_points  INTEGER,
    min_free_margin    REAL,
    min_margin_level   REAL,
    stop_if_equity_below REAL,
    copy_sl            INTEGER NOT NULL DEFAULT 1,
    copy_tp            INTEGER NOT NULL DEFAULT 1,
    sltp_mode          TEXT    NOT NULL DEFAULT 'ABSOLUTE',
    allow_stops_adjust INTEGER NOT NULL DEFAULT 0,
    copy_partial_close INTEGER NOT NULL DEFAULT 1,
    copy_pending       INTEGER NOT NULL DEFAULT 0,
    pending_price_mode TEXT    NOT NULL DEFAULT 'ABSOLUTE',
    allowed_symbols    TEXT    NOT NULL DEFAULT '',
    allowed_directions TEXT    NOT NULL DEFAULT 'BUY,SELL',
    max_price_deviation_percent REAL NOT NULL DEFAULT 3.0,
    auto_reconnect     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS symbol_map (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    terminal_id   TEXT NOT NULL REFERENCES terminals(id) ON DELETE CASCADE,
    master_symbol TEXT NOT NULL,
    slave_symbol  TEXT,
    status        TEXT NOT NULL DEFAULT 'UNMAPPED',
    note          TEXT,
    updated_at    TEXT,
    UNIQUE(terminal_id, master_symbol)
);

CREATE TABLE IF NOT EXISTS events (
    id                TEXT PRIMARY KEY,
    event_key         TEXT NOT NULL,
    type              TEXT NOT NULL,
    master_login      INTEGER NOT NULL,
    master_symbol     TEXT,
    master_position_id INTEGER,
    master_order_id   INTEGER,
    master_deal_id    INTEGER,
    side              TEXT,
    volume            REAL,
    volume_before     REAL,
    price             REAL,
    sl                REAL,
    tp                REAL,
    profit            REAL,
    payload           TEXT,
    state             TEXT NOT NULL DEFAULT 'DETECTED',
    detected_at_ms    INTEGER NOT NULL,
    processed_at_ms   INTEGER,
    UNIQUE(master_login, event_key)
);
CREATE INDEX IF NOT EXISTS idx_events_pos ON events(master_position_id);

CREATE TABLE IF NOT EXISTS event_actions (
    id             TEXT PRIMARY KEY,
    event_id       TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    terminal_id    TEXT NOT NULL REFERENCES terminals(id) ON DELETE CASCADE,
    state          TEXT NOT NULL DEFAULT 'QUEUED',
    attempts       INTEGER NOT NULL DEFAULT 0,
    params         TEXT,
    result         TEXT,
    error_code     INTEGER,
    error_message  TEXT,
    sent_at_ms     INTEGER,
    completed_at_ms INTEGER,
    latency_detect_us INTEGER,
    latency_total_us  INTEGER,
    UNIQUE(event_id, terminal_id)
);
CREATE INDEX IF NOT EXISTS idx_actions_term ON event_actions(terminal_id, state);

CREATE TABLE IF NOT EXISTS copy_mappings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    master_login        INTEGER NOT NULL,
    master_position_id  INTEGER NOT NULL,
    master_order_id     INTEGER,
    master_deal_id      INTEGER,
    master_symbol       TEXT NOT NULL,
    master_volume_initial  REAL,
    master_volume_current  REAL,
    slave_terminal_id   TEXT NOT NULL REFERENCES terminals(id) ON DELETE CASCADE,
    slave_symbol        TEXT,
    slave_position_id   INTEGER,
    slave_order_id      INTEGER,
    slave_deal_id       INTEGER,
    slave_volume_initial REAL,
    slave_volume_current REAL,
    status              TEXT NOT NULL DEFAULT 'OPEN',
    open_price_master   REAL,
    open_price_slave    REAL,
    deviation_percent   REAL,
    error_message       TEXT,
    created_at_ms       INTEGER NOT NULL,
    updated_at_ms       INTEGER,
    UNIQUE(slave_terminal_id, master_position_id)
);
CREATE INDEX IF NOT EXISTS idx_map_master ON copy_mappings(master_position_id, status);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
