"""Tests del setup: SL por ATR, TP a RR:1 y sizing por riesgo fijo."""

import numpy as np
import pandas as pd
import pytest

from bot.strategy.models import LONG, SHORT
from bot.strategy.setup import build_trade


def flat_df(price=100.0, spread=1.0, n=50):
    return pd.DataFrame(
        {
            "timestamp": np.arange(n) * 3_600_000,
            "open": np.full(n, price),
            "high": np.full(n, price + spread),
            "low": np.full(n, price - spread),
            "close": np.full(n, price),
            "volume": np.full(n, 100.0),
        }
    )


def test_sizing_pierde_el_riesgo_configurado(config):
    df = flat_df(price=100.0, spread=1.0)  # TR = 2 -> ATR = 2 -> SL a 3 (atr_mult 1.5)
    trade = build_trade(
        "BTC/USDT:USDT", LONG, 0, 100.0, df, equity=1000.0, available_margin=1000.0, config=config
    )
    assert trade is not None
    sl_distance = trade.entry_price - trade.initial_sl
    assert sl_distance == pytest.approx(3.0)
    # si salta el SL inicial se pierde el 1% del equity
    assert sl_distance * trade.size == pytest.approx(10.0)
    # TP a 3R
    assert trade.tp - trade.entry_price == pytest.approx(3 * sl_distance)
    assert trade.margin == pytest.approx(trade.size * trade.entry_price / config.leverage)


def test_sizing_respeta_margen_disponible(config):
    df = flat_df(price=100.0, spread=0.05)  # SL muy cercano -> posición enorme
    trade = build_trade(
        "BTC/USDT:USDT", LONG, 0, 100.0, df, equity=1000.0, available_margin=200.0, config=config
    )
    assert trade is not None
    assert trade.margin <= 200.0 + 1e-9


def test_short_niveles_invertidos(config):
    df = flat_df()
    trade = build_trade(
        "BTC/USDT:USDT", SHORT, 0, 100.0, df, equity=1000.0, available_margin=1000.0, config=config
    )
    assert trade.initial_sl > trade.entry_price > trade.tp


def test_sin_datos_suficientes_devuelve_none(config):
    df = flat_df(n=5)
    assert build_trade("X", LONG, 0, 100.0, df, 1000.0, 1000.0, config) is None


def test_sizing_capital_fraction(config):
    """Modo simulación: cada trade usa un % fijo del capital como margen."""
    config.sizing.mode = "capital_fraction"
    config.sizing.capital_fraction_pct = 10
    df = flat_df(price=100.0, spread=1.0)
    trade = build_trade(
        "BTC/USDT:USDT", LONG, 0, 100.0, df, equity=100.0, available_margin=100.0, config=config
    )
    assert trade is not None
    assert trade.margin == pytest.approx(10.0)  # 10% de 100 $
    assert trade.size * trade.entry_price == pytest.approx(10.0 * config.leverage)
    # respeta el margen disponible si es menor que la fracción
    trade2 = build_trade(
        "BTC/USDT:USDT", LONG, 0, 100.0, df, equity=100.0, available_margin=4.0, config=config
    )
    assert trade2.margin == pytest.approx(4.0)
