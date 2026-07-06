"""CLI del bot: `python -m bot fetch|backtest`."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date

from bot.config import load_config
from bot.data.exchange import Exchange
from bot.data.store import CandleStore

DAY_MS = 86_400_000


def cmd_fetch(args) -> None:
    config = load_config(args.config)
    exchange = Exchange(config.exchange)
    store = CandleStore(config.exchange)
    symbols = args.symbols.split(",") if args.symbols else config.universe
    now_ms = int(time.time() * 1000)
    # margen extra para el lookback de los indicadores en el arranque del backtest
    plan = [
        (config.timeframes.management, args.days),
        (config.timeframes.signal, args.days + 30),
        (config.timeframes.trend, args.days + 90),
    ]
    for symbol in symbols:
        for timeframe, days in plan:
            since = now_ms - days * DAY_MS
            df = store.update(exchange, symbol, timeframe, since, now_ms)
            print(f"  {symbol} {timeframe}: {len(df)} velas en cache", flush=True)
    print("Hecho.")


def cmd_backtest(args) -> None:
    from bot.backtest.engine import run_backtest

    config = load_config(args.config)
    result = run_backtest(
        config,
        date.fromisoformat(args.date_from),
        date.fromisoformat(args.date_to),
        persist=not args.no_persist,
    )
    print(f"\nBacktest {args.date_from} -> {args.date_to}"
          + (f"  (run #{result.run_id})" if result.run_id else ""))
    print("-" * 46)
    for key, value in result.metrics.items():
        print(f"  {key:26} {value}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="bot", description="conservative-bot CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="descarga/actualiza velas del exchange a la cache local")
    p_fetch.add_argument("--days", type=int, default=120)
    p_fetch.add_argument("--symbols", help="lista separada por comas (por defecto: universe del config)")
    p_fetch.add_argument("--config", default=None)
    p_fetch.set_defaults(func=cmd_fetch)

    p_bt = sub.add_parser("backtest", help="ejecuta un backtest sobre la cache local")
    p_bt.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    p_bt.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    p_bt.add_argument("--config", default=None)
    p_bt.add_argument("--no-persist", action="store_true", help="no guardar el run en la BD")
    p_bt.set_defaults(func=cmd_backtest)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
