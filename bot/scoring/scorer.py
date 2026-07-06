"""Scoring diario: combina las señales de los indicadores en una puntuación por token.

score en [-1, +1]: el signo decide LONG (+) o SHORT (-), la magnitud ordena el
ranking. Se abren los `trades_per_day` tokens con mayor |score| >= min_score.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.config import BotConfig
from bot.indicators.base import SignalContext
from bot.indicators.classic import (
    adx_signal,
    bollinger_signal,
    ema_trend_signal,
    macd_signal,
    rsi_signal,
)
from bot.indicators.frvp import frvp_signal

# Registro de indicadores disponibles. Para añadir uno nuevo: implementarlo,
# añadirlo aquí y darle peso en config.yaml (indicators:).
SIGNALS = {
    "ema_trend": ema_trend_signal,
    "rsi": rsi_signal,
    "macd": macd_signal,
    "adx": adx_signal,
    "bollinger": bollinger_signal,
    "frvp": frvp_signal,
}


@dataclass
class TokenScore:
    symbol: str
    score: float                       # con signo: + long, - short
    breakdown: dict[str, float] = field(default_factory=dict)

    @property
    def side(self) -> str:
        return "long" if self.score >= 0 else "short"


def score_token(symbol: str, ctx: SignalContext) -> TokenScore:
    cfg = ctx.config
    weights = {k: w for k, w in cfg.indicators.items() if k in SIGNALS and w > 0}
    total_weight = sum(weights.values()) or 1.0
    breakdown: dict[str, float] = {}
    composite = 0.0
    for name, weight in weights.items():
        signal = SIGNALS[name](ctx)
        breakdown[name] = round(signal, 4)
        composite += weight * signal
    return TokenScore(symbol=symbol, score=composite / total_weight, breakdown=breakdown)


def rank_tokens(scores: list[TokenScore], config: BotConfig) -> list[TokenScore]:
    """Filtra por puntuación mínima y devuelve los mejores candidatos del día."""
    eligible = [s for s in scores if abs(s.score) >= config.min_score]
    eligible.sort(key=lambda s: abs(s.score), reverse=True)
    return eligible[: config.trades_per_day]
