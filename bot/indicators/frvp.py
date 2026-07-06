"""FRVP: Fixed Range Volume Profile.

Construye el perfil de volumen de los últimos N días y calcula:
- POC (Point of Control): nivel de precio con más volumen
- Value Area (VAH/VAL): rango que concentra el `value_area_pct`% del volumen

Señal: precio por encima del VAH = ruptura alcista del área de valor (long),
por debajo del VAL = ruptura bajista (short), dentro del área = mercado en
rango (señal pequeña, sesgada por la posición respecto al POC).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from bot.indicators.base import SignalContext, clip


@dataclass
class VolumeProfile:
    poc: float
    vah: float
    val: float


def compute_frvp(df: pd.DataFrame, bins: int = 100, value_area_pct: float = 70.0) -> VolumeProfile | None:
    """Perfil de volumen: reparte el volumen de cada vela entre los bins que cubre su rango."""
    if len(df) < 10:
        return None
    lo, hi = df["low"].min(), df["high"].max()
    if hi <= lo:
        return None
    edges = np.linspace(lo, hi, bins + 1)
    volume = np.zeros(bins)
    idx_lo = np.clip(np.searchsorted(edges, df["low"].values, side="right") - 1, 0, bins - 1)
    idx_hi = np.clip(np.searchsorted(edges, df["high"].values, side="right") - 1, 0, bins - 1)
    for i0, i1, vol in zip(idx_lo, idx_hi, df["volume"].values):
        span = i1 - i0 + 1
        volume[i0 : i1 + 1] += vol / span
    total = volume.sum()
    if total <= 0:
        return None

    poc_idx = int(volume.argmax())
    # Value area: expandir desde el POC hacia el lado con más volumen
    included = {poc_idx}
    acc = volume[poc_idx]
    lo_i, hi_i = poc_idx, poc_idx
    target = total * value_area_pct / 100
    while acc < target and (lo_i > 0 or hi_i < bins - 1):
        below = volume[lo_i - 1] if lo_i > 0 else -1.0
        above = volume[hi_i + 1] if hi_i < bins - 1 else -1.0
        if above >= below:
            hi_i += 1
            acc += volume[hi_i]
            included.add(hi_i)
        else:
            lo_i -= 1
            acc += volume[lo_i]
            included.add(lo_i)

    centers = (edges[:-1] + edges[1:]) / 2
    return VolumeProfile(poc=float(centers[poc_idx]), vah=float(edges[hi_i + 1]), val=float(edges[lo_i]))


def frvp_signal(ctx: SignalContext) -> float:
    cfg = ctx.config.frvp
    df = ctx.signal_df
    # limitar al lookback configurado
    if df.empty:
        return 0.0
    last_ts = df["timestamp"].iloc[-1]
    window = df[df["timestamp"] >= last_ts - cfg.lookback_days * 86_400_000]
    profile = compute_frvp(window, bins=cfg.bins, value_area_pct=cfg.value_area_pct)
    if profile is None:
        return 0.0
    price = df["close"].iloc[-1]
    va_width = max(profile.vah - profile.val, 1e-12)
    if price > profile.vah:
        # ruptura por encima del área de valor: señal long creciente con la distancia
        return clip(0.7 + 0.3 * (price - profile.vah) / va_width, 0.0, 1.0)
    if price < profile.val:
        return clip(-0.7 - 0.3 * (profile.val - price) / va_width, -1.0, 0.0)
    # dentro del área de valor: mercado en rango, sesgo suave según lado del POC
    return clip(0.3 * 2 * (price - profile.poc) / va_width, -0.3, 0.3)
