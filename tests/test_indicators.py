"""Tests de indicadores y FRVP sobre series sintéticas."""

import numpy as np
import pandas as pd
import pytest

from bot.indicators.base import SignalContext
from bot.indicators.classic import (
    atr,
    bollinger_signal,
    ema_trend_signal,
    macd_signal,
    rsi,
    rsi_signal,
)
from bot.indicators.frvp import compute_frvp, frvp_signal


def make_df(closes, volumes=None, spread=0.5):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    return pd.DataFrame(
        {
            "timestamp": np.arange(n) * 3_600_000,
            "open": closes,
            "high": closes + spread,
            "low": closes - spread,
            "close": closes,
            "volume": volumes if volumes is not None else np.ones(n) * 100,
        }
    )


def ctx_for(df, config):
    return SignalContext(signal_df=df, trend_df=df, config=config)


def test_rsi_sube_con_serie_alcista():
    up = make_df(np.linspace(100, 150, 60))["close"]
    down = make_df(np.linspace(150, 100, 60))["close"]
    assert rsi(up).iloc[-1] > 70
    assert rsi(down).iloc[-1] < 30


def test_atr_positivo_y_escala():
    df = make_df(np.linspace(100, 110, 50), spread=1.0)
    a = atr(df).iloc[-1]
    assert a > 0
    df2 = make_df(np.linspace(100, 110, 50), spread=3.0)
    assert atr(df2).iloc[-1] > a  # más rango -> más ATR


def test_ema_trend_alcista_da_signal_positiva(config):
    df = make_df(np.linspace(100, 200, 250))
    assert ema_trend_signal(ctx_for(df, config)) == pytest.approx(1.0)
    df_down = make_df(np.linspace(200, 100, 250))
    assert ema_trend_signal(ctx_for(df_down, config)) == pytest.approx(-1.0)


def test_signals_en_rango_valido(config):
    rng = np.random.default_rng(42)
    closes = 100 + np.cumsum(rng.normal(0, 1, 300))
    df = make_df(np.abs(closes) + 50)
    for sig in (rsi_signal, macd_signal, bollinger_signal, ema_trend_signal, frvp_signal):
        v = sig(ctx_for(df, config))
        assert -1.0 <= v <= 1.0, sig.__name__


def test_frvp_poc_donde_hay_volumen():
    # 100 velas alrededor de 100 con mucho volumen, 20 velas a 110 con poco
    closes = np.concatenate([np.full(100, 100.0), np.full(20, 110.0)])
    volumes = np.concatenate([np.full(100, 1000.0), np.full(20, 10.0)])
    df = make_df(closes, volumes)
    profile = compute_frvp(df, bins=50, value_area_pct=70)
    assert profile is not None
    assert abs(profile.poc - 100.0) < 2.0
    assert profile.val <= profile.poc <= profile.vah


def test_frvp_signal_ruptura_alcista(config):
    # volumen concentrado en 100, precio actual rompe por encima del área de valor
    closes = np.concatenate([np.full(100, 100.0), [104.0]])
    volumes = np.concatenate([np.full(100, 1000.0), [50.0]])
    df = make_df(closes, volumes)
    assert frvp_signal(ctx_for(df, config)) >= 0.7
