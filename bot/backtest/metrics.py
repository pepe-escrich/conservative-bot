"""Métricas de rendimiento a partir de trades cerrados y curva de equity."""

from __future__ import annotations

import math

from bot.strategy.models import Trade


def compute_metrics(trades: list[Trade], equity_curve: list[tuple[int, float]], initial: float) -> dict:
    closed = [t for t in trades if t.status == "closed"]
    pnls = [t.realized_pnl for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    final_equity = equity_curve[-1][1] if equity_curve else initial
    gross_win = sum(wins)
    gross_loss = -sum(losses)

    # drawdown máximo sobre la curva de equity
    peak, max_dd = initial, 0.0
    for _, eq in equity_curve:
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak if peak > 0 else 0.0)

    # retornos diarios (entre snapshots consecutivos)
    daily_returns = []
    for (_, prev), (_, cur) in zip(equity_curve, equity_curve[1:]):
        if prev > 0:
            daily_returns.append(cur / prev - 1)
    days_above_target = sum(1 for r in daily_returns if r >= 0.01)

    n_days = max(len(daily_returns), 1)
    mean_r = sum(daily_returns) / n_days if daily_returns else 0.0
    std_r = (
        math.sqrt(sum((r - mean_r) ** 2 for r in daily_returns) / n_days) if daily_returns else 0.0
    )

    return {
        "initial_equity": round(initial, 2),
        "final_equity": round(final_equity, 2),
        "total_return_pct": round((final_equity / initial - 1) * 100, 2) if initial else 0.0,
        "num_trades": len(closed),
        "win_rate_pct": round(100 * len(wins) / len(closed), 1) if closed else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "total_fees": round(sum(t.fees_paid for t in closed), 2),
        "avg_trade_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0.0,
        "best_trade": round(max(pnls), 2) if pnls else 0.0,
        "worst_trade": round(min(pnls), 2) if pnls else 0.0,
        "avg_daily_return_pct": round(mean_r * 100, 3),
        "daily_return_std_pct": round(std_r * 100, 3),
        "days_above_1pct_target": days_above_target,
        "num_days": len(daily_returns),
        "close_reasons": _reason_counts(closed),
    }


def _reason_counts(closed: list[Trade]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in closed:
        counts[t.close_reason or "?"] = counts.get(t.close_reason or "?", 0) + 1
    return counts
