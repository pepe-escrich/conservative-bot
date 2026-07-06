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


# stablecoins y variantes wrapped/staked que no queremos tradear aunque estén en el top
UNIVERSE_EXCLUDE = {
    "USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "PYUSD", "USDS", "USD1", "BUSD", "USDD",
    "WBTC", "WETH", "STETH", "WSTETH", "WEETH", "WBETH", "CBBTC", "CBETH", "RETH", "METH",
    "RSETH", "TBTC", "LSETH", "SOLVBTC", "EZETH", "BGB", "LEO", "OKB", "CRO", "GT", "KCS",
}


def cmd_universe(args) -> None:
    """Genera el catálogo: top N por capitalización (CoinGecko) ∩ perpetuos USDT del exchange."""
    import requests

    config = load_config(args.config)
    exchange = Exchange(config.exchange)
    markets = exchange.client.load_markets()
    swaps = {
        m["base"]
        for m in markets.values()
        if m.get("swap") and m.get("quote") == "USDT" and m.get("settle") == "USDT" and m.get("active")
    }

    resp = requests.get(
        "https://api.coingecko.com/api/v3/coins/markets",
        params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": 250, "page": 1},
        headers={"User-Agent": "conservative-bot/0.1"},
        timeout=30,
    )
    resp.raise_for_status()
    coins = resp.json()

    selected: list[str] = []
    for coin in coins:
        sym = coin["symbol"].upper()
        name = (coin.get("name") or "").lower()
        if sym in UNIVERSE_EXCLUDE or "wrapped" in name or "staked" in name or "bridged" in name:
            continue
        if sym in swaps and f"{sym}/USDT:USDT" not in selected:
            selected.append(f"{sym}/USDT:USDT")
        if len(selected) >= args.top:
            break

    print(f"# top {len(selected)} por capitalización con perpetuo USDT en {config.exchange}")
    print("universe:")
    for s in selected:
        print(f"  - {s}")


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


def cmd_optimize(args) -> None:
    from bot.backtest.optimize import persist_run, run_study

    config = load_config(args.config)
    result = run_study(
        config,
        date.fromisoformat(args.date_from),
        date.fromisoformat(args.date_to),
        n_trials=args.trials,
        split=args.split,
        seed=args.seed,
    )
    print(f"\nInforme: {result.report_path}")
    print("\nConfiguración recomendada (mejor generalización OOS):")
    import yaml as _yaml

    print(_yaml.dump(result.recommended_overrides, sort_keys=False, allow_unicode=True))
    if not args.no_persist:
        run_id = persist_run(
            config, result.recommended_overrides, date.fromisoformat(args.date_from), date.fromisoformat(args.date_to)
        )
        print(f"Backtest completo con la config recomendada guardado como run #{run_id} (visible en la web).")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="bot", description="conservative-bot CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="descarga/actualiza velas del exchange a la cache local")
    p_fetch.add_argument("--days", type=int, default=120)
    p_fetch.add_argument("--symbols", help="lista separada por comas (por defecto: universe del config)")
    p_fetch.add_argument("--config", default=None)
    p_fetch.set_defaults(func=cmd_fetch)

    p_uni = sub.add_parser("universe", help="genera el catálogo top-N por capitalización (CoinGecko ∩ exchange)")
    p_uni.add_argument("--top", type=int, default=50)
    p_uni.add_argument("--config", default=None)
    p_uni.set_defaults(func=cmd_universe)

    p_bt = sub.add_parser("backtest", help="ejecuta un backtest sobre la cache local")
    p_bt.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    p_bt.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    p_bt.add_argument("--config", default=None)
    p_bt.add_argument("--no-persist", action="store_true", help="no guardar el run en la BD")
    p_bt.set_defaults(func=cmd_backtest)

    p_opt = sub.add_parser("optimize", help="estudio Optuna: busca los parámetros óptimos con validación IS/OOS")
    p_opt.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    p_opt.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    p_opt.add_argument("--trials", type=int, default=200)
    p_opt.add_argument("--split", type=float, default=0.65, help="fracción in-sample (resto out-of-sample)")
    p_opt.add_argument("--seed", type=int, default=42)
    p_opt.add_argument("--config", default=None)
    p_opt.add_argument("--no-persist", action="store_true", help="no guardar el run recomendado en la BD")
    p_opt.set_defaults(func=cmd_optimize)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
