"""Phase-1 technical validation script.

Run ON A WINDOWS MACHINE with at least one MT5 terminal installed and logged
into a DEMO account:

    python scripts/validate_connection.py "C:\\Program Files\\MetaTrader 5\\terminal64.exe"

It verifies (read-only, no orders are sent):
- MetaTrader5 package availability
- terminal attach, account info, terminal info
- positions / pending orders / recent history deals reads
- symbol specs read
"""
from __future__ import annotations

import datetime as dt
import sys


def main(terminal_path: str) -> int:
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("FATAL: MetaTrader5 package missing. Run: pip install MetaTrader5")
        return 1

    print(f"[1] initializing -> {terminal_path}")
    if not mt5.initialize(path=terminal_path):
        print(f"    FAILED: {mt5.last_error()}")
        return 2
    try:
        ver = ".".join(str(v) for v in mt5.version())
        print(f"    mt5 module version: {ver}")

        acc = mt5.account_info()
        if acc is None:
            print("    TERMINAL NOT LOGGED IN - open the terminal and login first")
            return 3
        print(f"[2] account: login={acc.login} server={acc.server} "
              f"currency={acc.currency} balance={acc.balance} "
              f"equity={acc.equity} margin_mode={acc.margin_mode} "
              f"(2=hedging, 0=netting)")
        term = mt5.terminal_info()
        print(f"[3] terminal: connected={term.connected} "
              f"autoTrading={term.trade_allowed}")

        poss = mt5.positions_get() or []
        print(f"[4] positions: {len(poss)}")
        for p in poss[:5]:
            print(f"    #{p.ticket} {p.symbol} {'BUY' if p.type == 0 else 'SELL'} "
                  f"{p.volume} @ {p.price_open} sl={p.sl} tp={p.tp}")

        orders = mt5.orders_get() or []
        print(f"[5] pending orders: {len(orders)}")

        to = dt.datetime.now() + dt.timedelta(minutes=1)
        frm = to - dt.timedelta(minutes=30)
        deals = mt5.history_deals_get(frm, to) or []
        print(f"[6] deals last 30min: {len(deals)}")

        sym = (poss[0].symbol if poss else "EURUSD")
        info = mt5.symbol_info(sym)
        if info:
            print(f"[7] symbol {sym}: digits={info.digits} point={info.point} "
                  f"vol {info.volume_min}-{info.volume_max} step={info.volume_step} "
                  f"stops_level={info.trade_stops_level} filling={info.filling_mode}")
        tick = mt5.symbol_info_tick(sym)
        if tick:
            print(f"    tick: bid={tick.bid} ask={tick.ask}")

        print("RESULT: ALL BASIC READS OK - this terminal is ready for use "
              "as a copy-trader endpoint (demo account strongly recommended).")
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python scripts/validate_connection.py <path-to-terminal64.exe>")
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
