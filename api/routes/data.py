"""Endpoints de lectura: resumen, equity, trades, PnL por intervalo y scores."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


def _db(request: Request):
    return request.app.state.db


def _config(request: Request):
    return request.app.state.config


def _win_stats(closed: list[dict]) -> dict:
    pnls = [t["realized_pnl"] for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [-p for p in pnls if p <= 0]
    return {
        "closed_trades": len(closed),
        "win_rate_pct": round(100 * len(wins) / len(closed), 1) if closed else None,
        "profit_factor": round(sum(wins) / sum(losses), 2) if sum(losses) > 0 else None,
        "total_fees": round(sum(t["fees_paid"] for t in closed), 2),
    }


@router.get("/summary")
def summary(request: Request, mode: str = "paper", run_id: int | None = None):
    db = _db(request)
    cfg = _config(request)

    if run_id is not None:
        run = db.get_run(run_id)
        if not run:
            raise HTTPException(404, "run no encontrado")
        metrics = json.loads(run["metrics_json"] or "{}")
        return {
            "source": f"backtest #{run_id}",
            "equity": metrics.get("final_equity"),
            "capital_inicial": metrics.get("initial_equity"),
            "total_return_pct": metrics.get("total_return_pct"),
            "open_trades": 0,
            "today_pnl": None,
            "today_pnl_pct": None,
            "metrics": metrics,
            **_win_stats(db.get_trades(run_id=run_id, status="closed", limit=10000)),
        }

    tz = ZoneInfo(cfg.schedule.timezone)
    today_start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    since_ms = int(today_start.timestamp() * 1000)
    fills_today = db.get_recent_fills(mode, since_ms)
    today_pnl = sum(f["pnl"] - f["fee"] for f in fills_today)

    equity = cfg.capital_inicial + db.total_realized_pnl(mode)
    open_trades = db.get_trades(mode=mode, status="open", limit=100)
    prices = db.get_prices()
    unrealized = 0.0
    for t in open_trades:
        price = prices.get(t["symbol"])
        if price:
            side = 1 if t["side"] == "long" else -1
            unrealized += side * (price - t["entry_price"]) * t["remaining_size"]

    start_of_day_equity = equity - today_pnl
    return {
        "source": mode,
        "equity": round(equity, 2),
        "unrealized_pnl": round(unrealized, 2),
        "capital_inicial": cfg.capital_inicial,
        "total_return_pct": round((equity / cfg.capital_inicial - 1) * 100, 2),
        "today_pnl": round(today_pnl, 2),
        "today_pnl_pct": round(100 * today_pnl / start_of_day_equity, 2) if start_of_day_equity else 0,
        "daily_target_pct": 1.0,
        "open_trades": len(open_trades),
        **_win_stats(db.get_trades(mode=mode, status="closed", limit=10000)),
    }


@router.get("/equity")
def equity_curve(request: Request, mode: str = "paper", run_id: int | None = None):
    return _db(request).get_equity_curve(mode, run_id)


@router.get("/trades")
def trades(
    request: Request,
    mode: str | None = None,
    run_id: int | None = None,
    status: str | None = None,
    symbol: str | None = None,
    limit: int = 200,
):
    db = _db(request)
    cfg = _config(request)
    rows = db.get_trades(mode=mode, run_id=run_id, status=status, symbol=symbol, limit=limit)
    prices = db.get_prices()
    for t in rows:
        side = 1 if t["side"] == "long" else -1
        price = prices.get(t["symbol"])
        if t["status"] == "open" and price:
            t["last_price"] = price
            t["unrealized_pnl"] = round(side * (price - t["entry_price"]) * t["remaining_size"], 4)
            t["unrealized_pnl_pct_margin"] = (
                round(100 * t["unrealized_pnl"] / t["margin"], 2) if t["margin"] else None
            )
        # precio del siguiente escalón, para la UI
        step_pct = cfg.steps.step_pct / 100
        if cfg.steps.basis == "margin_pnl":
            step_pct /= t["leverage"]
        t["next_step_price"] = t["entry_price"] * (1 + side * (t["steps_hit"] + 1) * step_pct)
    return rows


@router.get("/trades/{trade_id}/fills")
def trade_fills(request: Request, trade_id: int):
    return _db(request).get_fills(trade_id)


@router.get("/pnl")
def pnl_by_interval(
    request: Request, mode: str = "paper", run_id: int | None = None, interval: str = "day"
):
    """PnL realizado agregado por día/semana/mes (por fecha de cierre del trade)."""
    if interval not in ("day", "week", "month"):
        raise HTTPException(400, "interval debe ser day|week|month")
    db = _db(request)
    cfg = _config(request)
    tz = ZoneInfo(cfg.schedule.timezone)
    closed = db.get_trades(mode=mode if run_id is None else None, run_id=run_id, status="closed", limit=10000)

    buckets: dict[str, dict] = {}
    for t in closed:
        if t["close_time"] is None:
            continue
        dt = datetime.fromtimestamp(t["close_time"] / 1000, tz)
        if interval == "day":
            key = dt.date().isoformat()
        elif interval == "week":
            monday = dt.date() - timedelta(days=dt.weekday())
            key = monday.isoformat()
        else:
            key = f"{dt.year}-{dt.month:02d}"
        b = buckets.setdefault(key, {"bucket": key, "pnl": 0.0, "fees": 0.0, "trades": 0, "wins": 0})
        b["pnl"] += t["realized_pnl"]
        b["fees"] += t["fees_paid"]
        b["trades"] += 1
        b["wins"] += 1 if t["realized_pnl"] > 0 else 0

    out = sorted(buckets.values(), key=lambda b: b["bucket"])
    for b in out:
        b["pnl"] = round(b["pnl"], 4)
        b["fees"] = round(b["fees"], 4)
        b["win_rate_pct"] = round(100 * b["wins"] / b["trades"], 1) if b["trades"] else None
    return out


@router.get("/scores")
def scores(request: Request, mode: str = "paper", run_id: int | None = None, date: str | None = None):
    rows = _db(request).get_scores(date=date, mode=mode, run_id=run_id)
    for r in rows:
        r["breakdown"] = json.loads(r.pop("breakdown_json") or "{}")
    return rows


@router.get("/config")
def get_config(request: Request):
    return _config(request).model_dump()


@router.get("/profiles")
def get_profiles():
    """Perfiles de simulación: nombre -> overrides sobre config.yaml."""
    import yaml

    from bot.config import PROJECT_ROOT

    path = PROJECT_ROOT / "config" / "profiles.yaml"
    if not path.exists():
        return {"conservador": {}}
    with open(path) as f:
        return yaml.safe_load(f) or {"conservador": {}}


@router.get("/status")
def status(request: Request):
    cfg = _config(request)
    runner = getattr(request.app.state, "runner", None)
    return {
        "exchange": cfg.exchange,
        "universe": cfg.universe,
        "schedule": f"{cfg.schedule.time} {cfg.schedule.timezone}",
        "trades_per_day": cfg.trades_per_day,
        "leverage": cfg.leverage,
        "paper_enabled": cfg.paper.enabled,
        "paper_running": runner is not None,
    }
