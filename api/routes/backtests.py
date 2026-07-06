"""Endpoints de backtest: lanzar runs en background, consultar progreso y comparar."""

from __future__ import annotations

import json
import threading
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from bot.backtest.engine import BacktestEngine
from bot.config import BotConfig, load_config

router = APIRouter()


class BacktestRequest(BaseModel):
    date_from: date
    date_to: date
    overrides: dict = {}  # parcial, se fusiona sobre config.yaml


def _deep_merge(base: dict, overrides: dict) -> dict:
    out = dict(base)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@router.post("/backtests")
def launch_backtest(request: Request, body: BacktestRequest):
    if body.date_to < body.date_from:
        raise HTTPException(400, "date_to debe ser >= date_from")
    db = request.app.state.db
    base = load_config().model_dump()
    config = BotConfig(**_deep_merge(base, body.overrides))
    run_id = db.create_run(body.date_from.isoformat(), body.date_to.isoformat(), config.model_dump())

    def worker():
        engine = BacktestEngine(config, db=db, run_id=run_id)
        try:
            engine.run(body.date_from, body.date_to)
        except Exception as e:
            db.update_run(run_id, status="error", error=str(e))

    threading.Thread(target=worker, daemon=True, name=f"backtest-{run_id}").start()
    return {"run_id": run_id, "status": "running"}


@router.get("/backtests")
def list_backtests(request: Request):
    runs = request.app.state.db.get_runs()
    for r in runs:
        r["metrics"] = json.loads(r.pop("metrics_json") or "{}") or None
        r.pop("params_json", None)
    return runs


@router.get("/backtests/{run_id}")
def get_backtest(request: Request, run_id: int):
    run = request.app.state.db.get_run(run_id)
    if not run:
        raise HTTPException(404, "run no encontrado")
    run["metrics"] = json.loads(run.pop("metrics_json") or "{}") or None
    run["params"] = json.loads(run.pop("params_json") or "{}")
    return run


@router.delete("/backtests/{run_id}")
def delete_backtest(request: Request, run_id: int):
    db = request.app.state.db
    if not db.get_run(run_id):
        raise HTTPException(404, "run no encontrado")
    db.delete_run(run_id)
    return {"deleted": run_id}
