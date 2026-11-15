"""Core constants: enums, MT5-independent trading constants, error names.

Keep this module importable on any OS (Linux dev / Windows prod) without
importing the MetaTrader5 package.
"""
from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    MASTER = "MASTER"
    SLAVE = "SLAVE"


class EngineState(str, Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    EMERGENCY = "EMERGENCY"


class ConnectionState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"


class EventType(str, Enum):
    POSITION_OPEN = "POSITION_OPEN"
    POSITION_CLOSE_FULL = "POSITION_CLOSE_FULL"
    POSITION_CLOSE_PARTIAL = "POSITION_CLOSE_PARTIAL"
    POSITION_VOLUME_INCREASE = "POSITION_VOLUME_INCREASE"  # netting deposits
    POSITION_MODIFY_SLTP = "POSITION_MODIFY_SLTP"
    ORDER_PLACE = "ORDER_PLACE"
    ORDER_MODIFY = "ORDER_MODIFY"
    ORDER_REMOVE = "ORDER_REMOVE"
    ORDER_FILLED = "ORDER_FILLED"


# Event types that open new exposure on slaves.
OPENING_TYPES = {
    EventType.POSITION_OPEN.value,
    EventType.POSITION_VOLUME_INCREASE.value,
    EventType.ORDER_PLACE.value,
}

# Actions that are safe (and required) even while engine is PAUSED:
# managing already-copied positions is part of "preserve management of
# previous trades" policy.
MANAGEMENT_TYPES = {
    EventType.POSITION_CLOSE_FULL.value,
    EventType.POSITION_CLOSE_PARTIAL.value,
    EventType.POSITION_MODIFY_SLTP.value,
    EventType.ORDER_MODIFY.value,
    EventType.ORDER_REMOVE.value,
}


class EventState(str, Enum):
    DETECTED = "DETECTED"
    QUEUED = "QUEUED"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    FILLED = "FILLED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    PAUSED_SKIPPED = "PAUSED_SKIPPED"
    BLOCKED = "BLOCKED"


class ActionState(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    FILLED = "FILLED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class LotMode(str, Enum):
    SAME = "SAME"
    MULTIPLIER = "MULTIPLIER"
    FIXED = "FIXED"
    BALANCE_RATIO = "BALANCE_RATIO"
    EQUITY_RATIO = "EQUITY_RATIO"


class SlTpMode(str, Enum):
    ABSOLUTE = "ABSOLUTE"    # copy master SL/TP price levels as-is
    DISTANCE = "DISTANCE"    # keep distance from entry price


class PendingPriceMode(str, Enum):
    ABSOLUTE = "ABSOLUTE"
    DISTANCE = "DISTANCE"


class MappingStatus(str, Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    CLOSED = "CLOSED"
    PENDING_ORDER = "PENDING_ORDER"
    ERROR = "ERROR"
    RECONCILE = "RECONCILE"


class SymbolMapStatus(str, Enum):
    VERIFIED = "VERIFIED"      # trusted for trading
    SUGGESTED = "SUGGESTED"    # heuristic suggestion; NOT auto-traded
    UNMAPPED = "UNMAPPED"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


# ---- MT5 numeric constants (values from official MetaTrader5 package docs;
# duplicated here so engine/UI never need the native module) ----

ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
ORDER_TYPE_BUY_LIMIT = 2
ORDER_TYPE_SELL_LIMIT = 3
ORDER_TYPE_BUY_STOP = 4
ORDER_TYPE_SELL_STOP = 5
ORDER_TYPE_BUY_STOP_LIMIT = 6
ORDER_TYPE_SELL_STOP_LIMIT = 7

PENDING_ORDER_TYPES = {
    ORDER_TYPE_BUY_LIMIT,
    ORDER_TYPE_SELL_LIMIT,
    ORDER_TYPE_BUY_STOP,
    ORDER_TYPE_SELL_STOP,
    ORDER_TYPE_BUY_STOP_LIMIT,
    ORDER_TYPE_SELL_STOP_LIMIT,
}

DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1
DEAL_ENTRY_INOUT = 2
DEAL_ENTRY_OUT_BY = 3

# Order states that mean "still pending"
ORDER_STATE_ACTIVE = {0, 1, 5}  # STARTED, PLACED, PARTIAL(volume partially triggered)
ORDER_STATE_FILLED = 6
ORDER_STATE_CANCELED = 4
ORDER_STATE_REJECTED = 7

# Margin modes (account_info().margin_mode)
MARGIN_MODE_NETTING = 0
MARGIN_MODE_EXCHANGE = 1
MARGIN_MODE_HEDGING = 2

# Broker retcodes -> stable friendly names
RETCODES = {
    10004: "REQUOTE",
    10006: "REJECT",
    10007: "CANCEL",
    10008: "PLACED",
    10009: "DONE",
    10010: "DONE_PARTIAL",
    10011: "REQUEST_ERROR",
    10012: "TIMEOUT",
    10013: "INVALID_REQUEST",
    10014: "INVALID_VOLUME",
    10015: "INVALID_PRICE",
    10016: "INVALID_STOPS",
    10017: "TRADE_DISABLED",
    10018: "MARKET_CLOSED",
    10019: "NO_MONEY",
    10020: "PRICE_CHANGED",
    10021: "PRICE_OFF",
    10022: "INVALID_EXPIRATION",
    10023: "ORDER_CHANGED",
    10024: "TOO_MANY_REQUESTS",
    10025: "NO_CHANGES",
    10026: "AT_DISABLED_BY_SERVER",
    10027: "AT_DISABLED_BY_CLIENT",
    10028: "LOCKED",
    10029: "FROZEN",
    10030: "INVALID_FILL",
    10031: "CONNECTION",
    10032: "ONLY_REAL",
    10033: "LIMIT_ORDERS",
    10034: "LIMIT_VOLUME",
    10035: "INVALID_ORDER",
    10036: "POSITION_CLOSED",
}

# Retcodes that are safe to retry automatically after reconciliation.
RETRYABLE_RETCODES = {10012, 10020, 10031, 10021}

# Application identity
APP_NAME = "Trading Copier"
MAGIC_BASE = 47110000          # copied trades on slaves carry this magic
COMMENT_PREFIX = "TCPY"        # slave position comment prefix: "TCPY:<master_pos>"

# Volume epsilon for float comparisons
VOLUME_EPS = 1e-8
PRICE_EPS = 1e-8
