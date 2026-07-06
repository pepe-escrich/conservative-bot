"""Indicadores clásicos implementados con pandas/numpy (sin dependencias externas)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from bot.indicators.base import SignalContext, clip

# ---------------------------------------------------------------------------
# Cálculo de series
# ---------------------------------------------------------------------------


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    with np.errstate(divide="ignore"):
        rs = gain / loss  # loss 0 -> inf -> RSI 100
    return (100 - 100 / (1 + rs)).fillna(50.0)  # 0/0 (serie plana) -> 50


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / period, adjust=False).mean()


def adx(df: pd.DataFrame, period: int = 14):
    """Devuelve (+DI, -DI, ADX) con suavizado de Wilder."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    atr_s = true_range(df).ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_s
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_s
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_s = dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0.0)
    return plus_di.fillna(0.0), minus_di.fillna(0.0), adx_s


def bollinger(series: pd.Series, period: int = 20, mult: float = 2.0):
    mid = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = mid + mult * std
    lower = mid - mult * std
    return upper, mid, lower


# ---------------------------------------------------------------------------
# Señales en [-1, +1]
# ---------------------------------------------------------------------------


def ema_trend_signal(ctx: SignalContext) -> float:
    """Alineación de EMAs 20/50/200 en el timeframe de tendencia."""
    close = ctx.trend_df["close"]
    if len(close) < 60:
        return 0.0
    e20, e50, e200 = ema(close, 20).iloc[-1], ema(close, 50).iloc[-1], ema(close, 200).iloc[-1]
    price = close.iloc[-1]
    score = 0.0
    for bull in (price > e20, e20 > e50, e50 > e200):
        score += 1 / 3 if bull else -1 / 3
    return clip(score)


def rsi_signal(ctx: SignalContext) -> float:
    """RSI como momentum: >50 sesgo long, <50 short. Extremos (>80/<20) se atenúan."""
    close = ctx.signal_df["close"]
    if len(close) < 30:
        return 0.0
    r = rsi(close, 14).iloc[-1]
    s = clip((r - 50) / 25)
    if r > 80 or r < 20:
        s *= 0.5  # sobreextendido: menos fiable perseguirlo
    return s


def macd_signal(ctx: SignalContext) -> float:
    """Histograma MACD normalizado por su desviación típica reciente."""
    close = ctx.signal_df["close"]
    if len(close) < 60:
        return 0.0
    _, _, hist = macd(close)
    std = hist.tail(100).std()
    if not std or np.isnan(std):
        return 0.0
    return clip(hist.iloc[-1] / (2 * std))


def adx_signal(ctx: SignalContext) -> float:
    """Dirección por +DI/-DI, magnitud por fuerza de tendencia (ADX)."""
    df = ctx.signal_df
    if len(df) < 40:
        return 0.0
    plus_di, minus_di, adx_s = adx(df, 14)
    direction = 1.0 if plus_di.iloc[-1] >= minus_di.iloc[-1] else -1.0
    strength = clip(adx_s.iloc[-1] / 40, 0.0, 1.0)
    return direction * strength


def bollinger_signal(ctx: SignalContext) -> float:
    """%B centrado: por encima de la media -> long, por debajo -> short."""
    close = ctx.signal_df["close"]
    if len(close) < 25:
        return 0.0
    upper, _, lower = bollinger(close)
    width = upper.iloc[-1] - lower.iloc[-1]
    if not width or np.isnan(width):
        return 0.0
    pct_b = (close.iloc[-1] - lower.iloc[-1]) / width
    return clip((pct_b - 0.5) * 2)
