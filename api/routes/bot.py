"""Control del bot y de la cuenta: estado, start/stop, saldo y reset de KPIs."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger("api")
router = APIRouter()


class StartRequest(BaseModel):
    capital_fraction_pct: float | None = None  # % del capital por trade; None = config


class StopRequest(BaseModel):
    close_positions: bool = False


class ResetRequest(BaseModel):
    reference_amount: float | None = None  # None -> usar el saldo real de la cuenta
    close_positions: bool = False


def _runner(request: Request):
    return getattr(request.app.state, "runner", None)


@router.get("/account")
def account(request: Request):
    """Saldo real de la cuenta (si ejecución OKX), capital de referencia y estado del bot."""
    db = request.app.state.db
    cfg = request.app.state.config
    baseline = db.baseline_ms()
    reference = float(db.get_state("reference_capital", str(cfg.capital_inicial)))
    bot_pnl = db.total_realized_pnl("paper", since_ms=baseline)

    out = {
        "execution_mode": cfg.execution.mode,
        "demo": cfg.execution.demo,
        "running": _runner(request) is not None,
        "capital_fraction_pct": float(db.get_state("capital_fraction_pct", "10")),
        "reference_capital": round(reference, 2),
        "baseline_ts": baseline or None,
        "bot_equity": round(reference + bot_pnl, 2),
        "bot_pnl_since_reset": round(bot_pnl, 2),
        "balance": None,
        "balance_details": None,
    }
    if cfg.execution.mode == "okx":
        try:
            runner = _runner(request)
            broker = runner.broker if runner else None
            if broker is None:
                from bot.engine.okx_broker import OKXBroker

                broker = OKXBroker(cfg)
            bal = broker.balance()
            out["balance"] = bal["total_eq_usd"]
            out["balance_details"] = bal["details"]
        except Exception as e:
            out["balance_error"] = str(e)
    return out


@router.post("/bot/start")
def start_bot(request: Request, body: StartRequest):
    app = request.app
    if _runner(request) is not None:
        raise HTTPException(400, "el bot ya está en marcha")
    db = app.state.db
    if body.capital_fraction_pct is not None:
        if not 0 < body.capital_fraction_pct <= 100:
            raise HTTPException(400, "capital_fraction_pct debe estar entre 0 y 100")
        db.set_state("capital_fraction_pct", body.capital_fraction_pct)

    from bot.engine.runner import BotRunner

    try:
        runner = BotRunner(app.state.config, db)
        runner.start()
    except Exception as e:
        raise HTTPException(500, f"no se pudo arrancar el bot: {e}")
    app.state.runner = runner
    db.set_state("running", "1")
    return {
        "running": True,
        "capital_fraction_pct": float(db.get_state("capital_fraction_pct", "10")),
        "open_trades": len(runner.open_trades),
    }


@router.post("/bot/stop")
def stop_bot(request: Request, body: StopRequest):
    app = request.app
    runner = _runner(request)
    if runner is None:
        raise HTTPException(400, "el bot no está en marcha")
    closed = runner.stop(close_positions=body.close_positions)
    app.state.runner = None
    app.state.db.set_state("running", "0")
    return {"running": False, "closed_trades": closed}


@router.post("/bot/run-now")
def run_now(request: Request, entry: str | None = None):
    """Ejecuta ya el ciclo diario (scoring + apertura). Para pruebas: ?entry=market
    fuerza entrada a mercado aunque la config use pullback."""
    import threading

    runner = _runner(request)
    if runner is None:
        raise HTTPException(400, "el bot no está en marcha")
    if entry not in (None, "market", "pullback_limit"):
        raise HTTPException(400, "entry debe ser market o pullback_limit")

    def _run():
        try:
            runner.daily_job(entry_override=entry)
        except Exception:
            log.exception("run-now: el ciclo falló")

    threading.Thread(target=_run, daemon=True, name="run-now").start()
    return {"triggered": True, "entry": entry or "config"}


@router.post("/account/reset")
def reset_account(request: Request, body: ResetRequest):
    """Resetea los KPIs del bot: fija un nuevo capital de referencia y baseline.

    Los trades/equity anteriores quedan archivados (fuera de las métricas).
    """
    app = request.app
    db = app.state.db
    cfg = app.state.config
    runner = _runner(request)

    closed = 0
    if body.close_positions:
        if runner is not None:
            closed = runner.close_all("manual")
        else:
            # sin runner: marcar como cerrados los trades abiertos en BD (paper)
            open_rows = db.get_trades(mode="paper", status="open", limit=1000)
            if open_rows and cfg.execution.mode == "okx":
                raise HTTPException(400, "hay posiciones abiertas: arranca el bot para cerrarlas o ciérralas en OKX")

    reference = body.reference_amount
    if reference is None and cfg.execution.mode == "okx":
        try:
            from bot.engine.okx_broker import OKXBroker

            broker = runner.broker if runner else OKXBroker(cfg)
            reference = broker.balance()["total_eq_usd"]
        except Exception as e:
            raise HTTPException(500, f"no se pudo leer el saldo de OKX: {e}")
    if reference is None:
        reference = cfg.capital_inicial

    now_ms = int(time.time() * 1000)
    db.set_state("reference_capital", round(float(reference), 2))
    db.set_state("baseline_ts", now_ms)
    db.add_equity_snapshot("paper", now_ms, float(reference))
    log.info("reset de KPIs: referencia %.2f, baseline %d", reference, now_ms)
    return {"reference_capital": round(float(reference), 2), "baseline_ts": now_ms, "closed_trades": closed}
