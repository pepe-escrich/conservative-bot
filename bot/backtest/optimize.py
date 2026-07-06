"""Estudio de optimización de parámetros con Optuna (TPE, optimización bayesiana).

Busca los valores más idóneos de la estrategia maximizando una función de
fitness sobre el periodo *in-sample* (IS) y validando cada candidato sobre un
periodo *out-of-sample* (OOS) que el optimizador nunca ve. Sin esa separación,
el "mejor" resultado sería casi seguro sobreajuste.

Para que cada trial tarde segundos y no minutos, las señales de los
indicadores y el ATR se precalculan una sola vez por (día, símbolo): los
parámetros optimizados (gestión del trade, pesos del scoring, selección) no
cambian las señales base, solo cómo se combinan y cómo se gestiona el trade.

fitness = retorno_total_% - 0.5 * max_drawdown_%   (con mínimo de actividad)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import optuna
import pandas as pd
import yaml

from bot.config import DATA_DIR, BotConfig, with_overrides
from bot.backtest.engine import (
    SIGNAL_LOOKBACK_BARS,
    TREND_LOOKBACK_BARS,
    BacktestEngine,
)
from bot.data.store import CandleStore
from bot.indicators.base import SignalContext
from bot.indicators.classic import atr
from bot.persistence.db import Database
from bot.scoring.scorer import SIGNALS, TokenScore

log = logging.getLogger("optimize")

MIN_WEIGHT_SUM = 0.05


# ---------------------------------------------------------------------------
# Cache de señales
# ---------------------------------------------------------------------------


@dataclass
class SignalCache:
    days: list[date] = field(default_factory=list)
    # día -> símbolo -> {indicador: señal}
    breakdowns: dict[date, dict[str, dict[str, float]]] = field(default_factory=dict)
    # día -> símbolo -> ATR
    atrs: dict[date, dict[str, float]] = field(default_factory=dict)


def build_signal_cache(
    config: BotConfig,
    data: dict[str, dict[str, pd.DataFrame]],
    date_from: date,
    date_to: date,
) -> SignalCache:
    """Señales por indicador y ATR para cada (día, símbolo), sin lookahead."""
    tz = ZoneInfo(config.schedule.timezone)
    cache = SignalCache()
    n_days = (date_to - date_from).days + 1
    for i in range(n_days):
        day = date_from + timedelta(days=i)
        t0 = datetime.combine(day, dtime(config.schedule.hour, config.schedule.minute), tzinfo=tz)
        t0_ms = int(t0.timestamp() * 1000)
        day_breakdowns: dict[str, dict[str, float]] = {}
        day_atrs: dict[str, float] = {}
        for symbol, frames in data.items():
            signal_df = BacktestEngine._slice_before(frames["signal"], t0_ms, SIGNAL_LOOKBACK_BARS)
            trend_df = BacktestEngine._slice_before(frames["trend"], t0_ms, TREND_LOOKBACK_BARS)
            if len(signal_df) < 50 or len(trend_df) < 50:
                continue
            ctx = SignalContext(signal_df=signal_df, trend_df=trend_df, config=config)
            day_breakdowns[symbol] = {name: fn(ctx) for name, fn in SIGNALS.items()}
            day_atrs[symbol] = float(atr(signal_df, config.stop.atr_period).iloc[-1])
        cache.days.append(day)
        cache.breakdowns[day] = day_breakdowns
        cache.atrs[day] = day_atrs
    return cache


def make_providers(cache: SignalCache, weights: dict[str, float]):
    total = sum(weights.values())

    def scores_provider(day: date, _symbols: set[str]) -> list[TokenScore]:
        out = []
        for symbol, bd in cache.breakdowns.get(day, {}).items():
            composite = sum(weights[k] * bd[k] for k in weights if k in bd) / total
            out.append(TokenScore(symbol=symbol, score=composite, breakdown=bd))
        return out

    def atr_provider(day: date, symbol: str) -> float | None:
        return cache.atrs.get(day, {}).get(symbol)

    return scores_provider, atr_provider


# ---------------------------------------------------------------------------
# Espacio de búsqueda y fitness
# ---------------------------------------------------------------------------


def suggest_overrides(trial: optuna.Trial) -> dict:
    weights = {name: round(trial.suggest_float(f"w_{name}", 0.0, 1.0), 3) for name in SIGNALS}
    return {
        "trades_per_day": trial.suggest_int("trades_per_day", 1, 5),
        "min_score": round(trial.suggest_float("min_score", 0.1, 0.6), 3),
        "leverage": trial.suggest_categorical("leverage", [3, 5, 10, 15, 20]),
        "risk_per_trade_pct": round(trial.suggest_float("risk_per_trade_pct", 0.5, 2.0), 2),
        "risk_reward": round(trial.suggest_float("risk_reward", 1.5, 6.0), 2),
        "stop": {"atr_mult": round(trial.suggest_float("atr_mult", 0.8, 3.5), 2)},
        "steps": {
            "basis": trial.suggest_categorical("basis", ["margin_pnl", "price"]),
            "step_pct": round(trial.suggest_float("step_pct", 0.5, 8.0, log=True), 2),
            "partial_close_pct": round(trial.suggest_float("partial_close_pct", 20, 80), 1),
            "trail_mode": trial.suggest_categorical("trail_mode", ["previous_step", "breakeven_only"]),
        },
        "indicators": weights,
    }


def fitness(metrics: dict, min_trades: int) -> float:
    if metrics["num_trades"] < min_trades:
        return -100.0
    return metrics["total_return_pct"] - 0.5 * metrics["max_drawdown_pct"]


# ---------------------------------------------------------------------------
# Estudio
# ---------------------------------------------------------------------------


@dataclass
class StudyResult:
    study: optuna.Study
    best_overrides: dict
    recommended_overrides: dict
    report_path: Path
    is_range: tuple[date, date]
    oos_range: tuple[date, date]


def run_study(
    config: BotConfig,
    date_from: date,
    date_to: date,
    n_trials: int = 200,
    split: float = 0.65,
    seed: int = 42,
    store: CandleStore | None = None,
) -> StudyResult:
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    store = store or CandleStore(config.exchange)
    base_engine = BacktestEngine(config, store=store)
    data = base_engine._load_candles()
    if not data:
        raise RuntimeError("No hay velas en cache. Ejecuta primero: python -m bot fetch")

    all_days = [(date_from + timedelta(days=i)) for i in range((date_to - date_from).days + 1)]
    cut = max(1, int(len(all_days) * split))
    is_from, is_to = all_days[0], all_days[cut - 1]
    oos_from, oos_to = all_days[min(cut, len(all_days) - 1)], all_days[-1]
    min_trades_is = max(10, int(0.3 * cut))

    print(f"Precalculando señales de {len(data)} símbolos × {len(all_days)} días…", flush=True)
    cache = build_signal_cache(config, data, date_from, date_to)
    print(f"In-sample: {is_from} → {is_to} · Out-of-sample: {oos_from} → {oos_to}", flush=True)

    def run_range(cfg: BotConfig, weights: dict[str, float], d0: date, d1: date) -> dict:
        scores_p, atr_p = make_providers(cache, weights)
        engine = BacktestEngine(cfg, store=store, data=data, scores_provider=scores_p, atr_provider=atr_p)
        return engine.run(d0, d1).metrics

    def objective(trial: optuna.Trial) -> float:
        overrides = suggest_overrides(trial)
        weights = overrides["indicators"]
        if sum(weights.values()) < MIN_WEIGHT_SUM:
            raise optuna.TrialPruned()
        cfg = with_overrides(config, overrides)
        m_is = run_range(cfg, weights, is_from, is_to)
        m_oos = run_range(cfg, weights, oos_from, oos_to)
        trial.set_user_attr("is_metrics", m_is)
        trial.set_user_attr("oos_metrics", m_oos)
        trial.set_user_attr("overrides", overrides)
        return fitness(m_is, min_trades_is)

    def progress(study: optuna.Study, trial: optuna.FrozenTrial) -> None:
        if (trial.number + 1) % 20 == 0:
            best = study.best_trial
            print(
                f"  trial {trial.number + 1}/{n_trials} · mejor fitness IS {study.best_value:.2f} "
                f"(trial {best.number}, OOS ret {best.user_attrs.get('oos_metrics', {}).get('total_return_pct', '?')}%)",
                flush=True,
            )

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=n_trials, callbacks=[progress])

    # top-10 IS; recomendación = el que mejor generaliza (mayor fitness OOS) entre ellos
    completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE and t.value is not None]
    top = sorted(completed, key=lambda t: t.value, reverse=True)[:10]
    min_trades_oos = max(5, int(0.2 * (len(all_days) - cut)))
    recommended = max(top, key=lambda t: fitness(t.user_attrs["oos_metrics"], min_trades_oos))

    report_path = _write_report(
        study, top, recommended, config, date_from, date_to, (is_from, is_to), (oos_from, oos_to), n_trials
    )
    return StudyResult(
        study=study,
        best_overrides=study.best_trial.user_attrs["overrides"],
        recommended_overrides=recommended.user_attrs["overrides"],
        report_path=report_path,
        is_range=(is_from, is_to),
        oos_range=(oos_from, oos_to),
    )


def _fmt_metrics(m: dict) -> str:
    return (
        f"ret {m['total_return_pct']:+.2f}% · dd {m['max_drawdown_pct']:.2f}% · "
        f"{m['num_trades']} trades · wr {m['win_rate_pct']}% · pf {m['profit_factor']} · fees {m['total_fees']}$"
    )


def _write_report(
    study, top, recommended, config, date_from, date_to, is_range, oos_range, n_trials
) -> Path:
    out_dir = DATA_DIR / "studies"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"study_{datetime.now().strftime('%Y%m%d_%H%M')}.md"

    lines = [
        "# Estudio de optimización de parámetros",
        "",
        f"- Rango: {date_from} → {date_to} · {n_trials} trials (TPE)",
        f"- In-sample: {is_range[0]} → {is_range[1]} · Out-of-sample: {oos_range[0]} → {oos_range[1]}",
        f"- Universo: {len(config.universe)} tokens · fees taker {config.fees.taker_pct}% · slippage {config.fees.slippage_pct}%",
        "",
        "## Top 10 (por fitness in-sample)",
        "",
        "| # | fitness IS | IS | OOS |",
        "|---|-----------|----|-----|",
    ]
    for t in top:
        mark = " ⭐" if t.number == recommended.number else ""
        lines.append(
            f"| {t.number}{mark} | {t.value:.2f} | {_fmt_metrics(t.user_attrs['is_metrics'])} | "
            f"{_fmt_metrics(t.user_attrs['oos_metrics'])} |"
        )

    lines += [
        "",
        "⭐ = configuración recomendada (la que mejor generaliza en out-of-sample dentro del top-10).",
        "",
        "## Importancia de parámetros",
        "",
    ]
    try:
        importances = optuna.importance.get_param_importances(
            study, evaluator=optuna.importance.PedAnovaImportanceEvaluator()
        )
        for name, value in list(importances.items())[:12]:
            lines.append(f"- {name}: {value:.3f}")
    except Exception as e:  # evaluador no disponible: no es crítico
        lines.append(f"(no disponible: {e})")

    lines += [
        "",
        "## Configuración recomendada (pegar en config/config.yaml)",
        "",
        "```yaml",
        yaml.dump(recommended.user_attrs["overrides"], sort_keys=False, allow_unicode=True).rstrip(),
        "```",
        "",
    ]
    path.write_text("\n".join(lines))
    return path


def persist_run(config: BotConfig, overrides: dict, date_from: date, date_to: date) -> int:
    """Guarda en la BD un backtest completo con la config dada (visible en la UI)."""
    from bot.backtest.engine import run_backtest

    cfg = with_overrides(config, overrides)
    result = run_backtest(cfg, date_from, date_to, db=Database(), persist=True)
    return result.run_id
