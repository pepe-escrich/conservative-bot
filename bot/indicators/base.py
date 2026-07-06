"""Interfaz de los indicadores de señal.

Cada indicador es una función que recibe el contexto de mercado de un símbolo
y devuelve una señal en [-1, +1]: -1 short fuerte, 0 neutro, +1 long fuerte.
Para añadir un indicador nuevo: implementar la función, registrarla en
`bot.scoring.scorer.SIGNALS` y darle peso en config.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from bot.config import BotConfig


@dataclass
class SignalContext:
    """Velas disponibles para calcular señales de un símbolo (hasta el momento de decisión)."""

    signal_df: pd.DataFrame  # timeframe de señal (p. ej. 1h)
    trend_df: pd.DataFrame   # timeframe de tendencia (p. ej. 4h)
    config: BotConfig


def clip(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))
