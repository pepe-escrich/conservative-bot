"""Motor de backtest.

Simula la operativa día a día:
1. A la hora programada (p. ej. 07:00 Europe/Madrid) puntúa el catálogo con
   las velas disponibles hasta ese instante (sin lookahead).
2. Abre los top-N trades al open de la primera vela de gestión.
3. Gestiona todos los trades abiertos con las velas del timeframe de gestión
   (escalones, trailing, SL, TP) hasta que cierren; pueden durar varios días.
4. Comisiones y slippage en cada fill. Snapshot de equity al final de cada día.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from bot.config import BotConfig
from bot.data.store import CandleStore
from bot.backtest.metrics import compute_metrics
from bot.indicators.base import SignalContext
from bot.persistence.db import Database
from bot.scoring.scorer import TokenScore, rank_tokens, score_token
from bot.strategy.manager import StepLadderManager
from bot.strategy.models import OPEN, Trade
from bot.strategy.setup import build_trade, side_from_score

SIGNAL_LOOKBACK_BARS = 500
TREND_LOOKBACK_BARS = 400


@dataclass
class BacktestResult:
    run_id: int | None
    trades: list[Trade]
    equity_curve: list[tuple[int, float]]
    metrics: dict = field(default_factory=dict)


class BacktestEngine:
    def __init__(
        self,
        config: BotConfig,
        store: CandleStore | None = None,
        db: Database | None = None,
        run_id: int | None = None,
        progress_cb: Callable[[float], None] | None = None,
        data: dict[str, dict[str, pd.DataFrame]] | None = None,
        scores_provider: Callable[[date, set[str]], list[TokenScore]] | None = None,
        atr_provider: Callable[[date, str], float | None] | None = None,
    ):
        """`data`, `scores_provider` y `atr_provider` permiten inyectar velas ya
        cargadas y señales precalculadas (los usa el optimizador para no repetir
        el cálculo de indicadores en cada trial)."""
        self.config = config
        self.store = store or CandleStore(config.exchange)
        self.db = db
        self.run_id = run_id
        self.progress_cb = progress_cb
        self.data = data
        self.scores_provider = scores_provider
        self.atr_provider = atr_provider
        self.manager = StepLadderManager(config)

    # ------------------------------------------------------------------

    def _load_candles(self) -> dict[str, dict[str, pd.DataFrame]]:
        tf = self.config.timeframes
        data: dict[str, dict[str, pd.DataFrame]] = {}
        for symbol in self.config.universe:
            frames = {
                "signal": self.store.load(symbol, tf.signal),
                "trend": self.store.load(symbol, tf.trend),
                "mgmt": self.store.load(symbol, tf.management),
            }
            if all(not f.empty for f in frames.values()):
                data[symbol] = frames
        return data

    @staticmethod
    def _slice_before(df: pd.DataFrame, ts_ms: int, tail: int) -> pd.DataFrame:
        idx = int(np.searchsorted(df["timestamp"].values, ts_ms, side="left"))
        return df.iloc[max(0, idx - tail) : idx]

    @staticmethod
    def _slice_window(df: pd.DataFrame, start_ms: int, end_ms: int) -> pd.DataFrame:
        ts = df["timestamp"].values
        i0 = int(np.searchsorted(ts, start_ms, side="left"))
        i1 = int(np.searchsorted(ts, end_ms, side="left"))
        return df.iloc[i0:i1]

    # ------------------------------------------------------------------

    def run(self, date_from: date, date_to: date) -> BacktestResult:
        cfg = self.config
        tz = ZoneInfo(cfg.schedule.timezone)
        data = self.data if self.data is not None else self._load_candles()
        if not data:
            raise RuntimeError(
                "No hay velas en cache. Ejecuta primero: python -m bot fetch --days N"
            )

        equity = cfg.capital_inicial
        open_trades: list[Trade] = []
        all_trades: list[Trade] = []
        equity_curve: list[tuple[int, float]] = []

        days = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
        for day_idx, day in enumerate(days):
            t0 = datetime.combine(day, dtime(cfg.schedule.hour, cfg.schedule.minute), tzinfo=tz)
            t0_ms = int(t0.timestamp() * 1000)
            day_end_ms = int((t0 + timedelta(days=1)).timestamp() * 1000)

            # --- 1) scoring del día ---------------------------------------
            busy = {t.symbol for t in open_trades}
            if self.scores_provider is not None:
                scores = self.scores_provider(day, set(data))
            else:
                scores = []
                for symbol, frames in data.items():
                    signal_df = self._slice_before(frames["signal"], t0_ms, SIGNAL_LOOKBACK_BARS)
                    trend_df = self._slice_before(frames["trend"], t0_ms, TREND_LOOKBACK_BARS)
                    if len(signal_df) < 50 or len(trend_df) < 50:
                        continue
                    ctx = SignalContext(signal_df=signal_df, trend_df=trend_df, config=cfg)
                    scores.append(score_token(symbol, ctx))

            candidates = [s for s in rank_tokens(scores, cfg) if s.symbol not in busy]

            # --- 2) apertura de trades ------------------------------------
            new_trades: list[Trade] = []
            for cand in candidates:
                frames = data[cand.symbol]
                day_mgmt = self._slice_window(frames["mgmt"], t0_ms, day_end_ms)
                if day_mgmt.empty:
                    continue
                first = day_mgmt.iloc[0]
                reserved = sum(t.margin * (t.remaining_size / t.size) for t in open_trades)
                atr_value = self.atr_provider(day, cand.symbol) if self.atr_provider else None
                if self.atr_provider is not None and atr_value is None:
                    continue
                signal_df = (
                    frames["signal"].iloc[:0]
                    if atr_value is not None
                    else self._slice_before(frames["signal"], t0_ms, SIGNAL_LOOKBACK_BARS)
                )
                trade = build_trade(
                    cand.symbol,
                    side_from_score(cand.score),
                    int(first["timestamp"]),
                    float(first["open"]),
                    signal_df,
                    equity=equity,
                    available_margin=max(equity - reserved, 0.0),
                    config=cfg,
                    score=cand.score,
                    mode="backtest",
                    atr_value=atr_value,
                )
                if trade is None:
                    continue
                equity -= trade.fills[0].fee  # comisión de apertura
                new_trades.append(trade)
                open_trades.append(trade)
                all_trades.append(trade)

            if self.db is not None:
                self.db.save_scores(
                    "backtest", day.isoformat(), scores, {t.symbol for t in new_trades}, self.run_id
                )

            # --- 3) gestión intradía --------------------------------------
            for trade in list(open_trades):
                start = trade.entry_time if trade in new_trades else t0_ms
                window = self._slice_window(data[trade.symbol]["mgmt"], start, day_end_ms)
                for row in window.itertuples(index=False):
                    fills = self.manager.on_candle(
                        trade, int(row.timestamp), float(row.open), float(row.high), float(row.low), float(row.close)
                    )
                    for f in fills:
                        equity += f.pnl - f.fee
                    if trade.status != OPEN:
                        break
                if trade.status != OPEN:
                    open_trades.remove(trade)
                    if self.db is not None:
                        self.db.save_trade(trade, self.run_id)

            equity_curve.append((day_end_ms, equity))
            if self.db is not None:
                self.db.add_equity_snapshot("backtest", day_end_ms, equity, self.run_id)
                self.db.update_run(self.run_id, progress=round((day_idx + 1) / len(days), 3))
            if self.progress_cb:
                self.progress_cb((day_idx + 1) / len(days))

        # --- 4) cierre forzoso al final del rango --------------------------
        for trade in list(open_trades):
            df = data[trade.symbol]["mgmt"]
            past = df[df["timestamp"] < equity_curve[-1][0]] if equity_curve else df
            last = past.iloc[-1] if not past.empty else df.iloc[-1]
            fills = self.manager.force_close(trade, int(last["timestamp"]), float(last["close"]))
            for f in fills:
                equity += f.pnl - f.fee
            if self.db is not None:
                self.db.save_trade(trade, self.run_id)
        open_trades.clear()
        if equity_curve:
            equity_curve[-1] = (equity_curve[-1][0], equity)

        metrics = compute_metrics(all_trades, equity_curve, cfg.capital_inicial)
        if self.db is not None:
            self.db.update_run(self.run_id, status="done", progress=1.0, metrics=metrics)
        return BacktestResult(self.run_id, all_trades, equity_curve, metrics)


def run_backtest(
    config: BotConfig,
    date_from: date,
    date_to: date,
    db: Database | None = None,
    persist: bool = True,
) -> BacktestResult:
    """Punto de entrada: crea el run en BD (si procede) y ejecuta el motor."""
    run_id = None
    if persist:
        db = db or Database()
        run_id = db.create_run(date_from.isoformat(), date_to.isoformat(), config.model_dump())
    else:
        db = None
    engine = BacktestEngine(config, db=db, run_id=run_id)
    try:
        return engine.run(date_from, date_to)
    except Exception as e:
        if db is not None and run_id is not None:
            db.update_run(run_id, status="error", error=str(e))
        raise
