"""Data models shared between workers, engine and UI.

Pure dataclasses with JSON (de)serialization - the IPC layer sends these
as JSON payloads.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field


@dataclass
class Position:
    ticket: int
    symbol: str
    type: int                # 0=BUY 1=SELL
    volume: float
    price_open: float
    sl: float = 0.0
    tp: float = 0.0
    price_current: float = 0.0
    profit: float = 0.0
    swap: float = 0.0
    time_msc: int = 0
    magic: int = 0
    comment: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Position":
        return Position(
            ticket=int(d["ticket"]),
            symbol=str(d["symbol"]),
            type=int(d["type"]),
            volume=float(d["volume"]),
            price_open=float(d["price_open"]),
            sl=float(d.get("sl", 0.0)),
            tp=float(d.get("tp", 0.0)),
            price_current=float(d.get("price_current", 0.0)),
            profit=float(d.get("profit", 0.0)),
            swap=float(d.get("swap", 0.0)),
            time_msc=int(d.get("time_msc", 0)),
            magic=int(d.get("magic", 0)),
            comment=str(d.get("comment", "")),
        )


@dataclass
class PendingOrder:
    ticket: int
    symbol: str
    type: int                # ORDER_TYPE_*
    volume_initial: float
    volume_current: float
    price_open: float
    sl: float = 0.0
    tp: float = 0.0
    state: int = 0
    time_setup_msc: int = 0
    magic: int = 0
    comment: str = ""
    position_id: int = 0

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "PendingOrder":
        return PendingOrder(
            ticket=int(d["ticket"]),
            symbol=str(d["symbol"]),
            type=int(d["type"]),
            volume_initial=float(d.get("volume_initial", 0.0)),
            volume_current=float(d.get("volume_current", 0.0)),
            price_open=float(d.get("price_open", 0.0)),
            sl=float(d.get("sl", 0.0)),
            tp=float(d.get("tp", 0.0)),
            state=int(d.get("state", 0)),
            time_setup_msc=int(d.get("time_setup_msc", 0)),
            magic=int(d.get("magic", 0)),
            comment=str(d.get("comment", "")),
            position_id=int(d.get("position_id", 0)),
        )


@dataclass
class Deal:
    ticket: int
    order: int
    position_id: int
    symbol: str
    type: int                # 0=BUY 1=SELL
    entry: int               # 0=IN 1=OUT 2=INOUT 3=OUT_BY
    volume: float
    price: float
    profit: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    time_msc: int = 0
    comment: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Deal":
        return Deal(
            ticket=int(d["ticket"]),
            order=int(d.get("order", 0)),
            position_id=int(d.get("position_id", 0)),
            symbol=str(d.get("symbol", "")),
            type=int(d.get("type", 0)),
            entry=int(d.get("entry", 0)),
            volume=float(d.get("volume", 0.0)),
            price=float(d.get("price", 0.0)),
            profit=float(d.get("profit", 0.0)),
            commission=float(d.get("commission", 0.0)),
            swap=float(d.get("swap", 0.0)),
            time_msc=int(d.get("time_msc", 0)),
            comment=str(d.get("comment", "")),
        )


@dataclass
class SymbolSpecs:
    symbol: str
    digits: int = 5
    point: float = 0.0
    tick_size: float = 0.0
    spread_points: int = 0
    trade_mode: int = 0
    trade_stops_level: int = 0
    trade_freeze_level: int = 0
    filling_mode: int = 0        # bitmask: 1=FOK, 2=IOC
    volume_min: float = 0.0
    volume_max: float = 0.0
    volume_step: float = 0.0
    contract_size: float = 0.0
    trade_exec_mode: int = 0

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "SymbolSpecs":
        return SymbolSpecs(
            symbol=str(d.get("symbol", "")),
            digits=int(d.get("digits", 5)),
            point=float(d.get("point", 0.0)),
            tick_size=float(d.get("tick_size", 0.0)),
            spread_points=int(d.get("spread_points", 0)),
            trade_mode=int(d.get("trade_mode", 0)),
            trade_stops_level=int(d.get("trade_stops_level", 0)),
            trade_freeze_level=int(d.get("trade_freeze_level", 0)),
            filling_mode=int(d.get("filling_mode", 0)),
            volume_min=float(d.get("volume_min", 0.0)),
            volume_max=float(d.get("volume_max", 0.0)),
            volume_step=float(d.get("volume_step", 0.0)),
            contract_size=float(d.get("contract_size", 0.0)),
            trade_exec_mode=int(d.get("trade_exec_mode", 0)),
        )


@dataclass
class AccountSnapshot:
    """Full periodic snapshot of one terminal, produced by its worker."""
    terminal_id: str = ""
    login: int = 0
    account_name: str = ""
    server: str = ""
    currency: str = ""
    leverage: int = 0
    margin_mode: int = 0        # 0 netting / 1 exchange / 2 hedging
    trade_allowed: bool = False       # account algo trading allowed
    terminal_trade_allowed: bool = False  # terminal AutoTrading button
    connected_to_broker: bool = False
    balance: float = 0.0
    equity: float = 0.0
    margin: float = 0.0
    margin_free: float = 0.0
    margin_level: float = 0.0
    profit: float = 0.0
    positions: list = field(default_factory=list)   # list[dict]
    orders: list = field(default_factory=list)      # list[dict] (pending)
    deals: list = field(default_factory=list)       # recent deals window (master only)
    deal_window_from_ms: int = 0
    ts_utc_ms: int = 0
    ts_monotonic: float = 0.0

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "AccountSnapshot":
        return AccountSnapshot(
            terminal_id=str(d.get("terminal_id", "")),
            login=int(d.get("login", 0)),
            account_name=str(d.get("account_name", "")),
            server=str(d.get("server", "")),
            currency=str(d.get("currency", "")),
            leverage=int(d.get("leverage", 0)),
            margin_mode=int(d.get("margin_mode", 0)),
            trade_allowed=bool(d.get("trade_allowed", False)),
            terminal_trade_allowed=bool(d.get("terminal_trade_allowed", False)),
            connected_to_broker=bool(d.get("connected_to_broker", False)),
            balance=float(d.get("balance", 0.0)),
            equity=float(d.get("equity", 0.0)),
            margin=float(d.get("margin", 0.0)),
            margin_free=float(d.get("margin_free", 0.0)),
            margin_level=float(d.get("margin_level", 0.0)),
            profit=float(d.get("profit", 0.0)),
            positions=list(d.get("positions", [])),
            orders=list(d.get("orders", [])),
            deals=list(d.get("deals", [])),
            deal_window_from_ms=int(d.get("deal_window_from_ms", 0)),
            ts_utc_ms=int(d.get("ts_utc_ms", 0)),
            ts_monotonic=float(d.get("ts_monotonic", 0.0)),
        )
