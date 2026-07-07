"""Tests de la entrada por límite en pullback (motor de backtest)."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from bot.backtest.engine import BacktestEngine
from bot.config import BotConfig
from bot.data.store import CandleStore
from bot.strategy.models import LONG
from bot.strategy.setup import build_trade
from tests.test_backtest import DAY_MS, START_MS, SYMBOL, synth_candles
from tests.test_setup import flat_df


def test_build_trade_limit_usa_maker_y_sin_slippage(config):
    config.fees.taker_pct = 0.1
    config.fees.maker_pct = 0.02
    config.fees.slippage_pct = 0.05
    df = flat_df(price=100.0, spread=1.0)

    market = build_trade("X", LONG, 0, 100.0, df, 1000.0, 1000.0, config, entry_type="market")
    limit = build_trade("X", LONG, 0, 100.0, df, 1000.0, 1000.0, config, entry_type="limit")

    assert market.entry_price == pytest.approx(100.05)  # slippage en contra
    assert limit.entry_price == pytest.approx(100.0)    # la limitada llena a su precio
    market_fee_pct = market.fills[0].fee / (market.size * market.entry_price) * 100
    limit_fee_pct = limit.fills[0].fee / (limit.size * limit.entry_price) * 100
    assert market_fee_pct == pytest.approx(0.1)
    assert limit_fee_pct == pytest.approx(0.02)


def _store_with_synth(tmp_path):
    store = CandleStore("test", base_dir=tmp_path)
    end = START_MS + 60 * DAY_MS
    store.save(SYMBOL, "1h", synth_candles(3_600_000, START_MS, end))
    store.save(SYMBOL, "4h", synth_candles(14_400_000, START_MS, end))
    store.save(SYMBOL, "5m", synth_candles(300_000, START_MS, end))
    return store


def _config(**entry) -> BotConfig:
    return BotConfig(
        universe=[SYMBOL],
        min_score=0.0,
        capital_inicial=1000,
        fees={"taker_pct": 0.05, "maker_pct": 0.02, "slippage_pct": 0.0},
        entry=entry,
    )


def test_pullback_llena_y_entra_con_maker(tmp_path):
    # la serie sintética oscila ±0.4%: un pullback de 0.1% llena casi siempre
    store = _store_with_synth(tmp_path)
    config = _config(mode="pullback_limit", pullback_pct=0.1, timeout_hours=24, on_timeout="cancel")
    result = BacktestEngine(config, store=store).run(date(2026, 2, 10), date(2026, 2, 20))

    m = result.metrics
    assert m["entry_orders"] > 0
    assert m["entry_filled"] > 0
    assert m["entry_orders"] == m["entry_filled"] + m["entry_cancelled"] + m["entry_timeout_market"]
    # todo fill limitado paga maker y entra al precio límite o mejor
    for t in result.trades:
        fee_pct = t.fills[0].fee / (t.size * t.entry_price) * 100
        assert fee_pct == pytest.approx(0.02)


def test_pullback_imposible_no_abre_trades(tmp_path):
    # un retroceso del 30% nunca ocurre en la serie sintética -> todo expira cancelado
    store = _store_with_synth(tmp_path)
    config = _config(mode="pullback_limit", pullback_pct=30.0, timeout_hours=4, on_timeout="cancel")
    result = BacktestEngine(config, store=store).run(date(2026, 2, 10), date(2026, 2, 14))

    m = result.metrics
    assert m["num_trades"] == 0
    assert m["entry_filled"] == 0
    assert m["entry_cancelled"] == m["entry_orders"] > 0


def test_fill_de_limitada_no_usa_el_high_previo_de_su_vela(tmp_path):
    """Regresión anti-lookahead: el high de la vela que ejecuta la limitada suele
    ocurrir ANTES del fill; no puede contarse como recorrido favorable posterior."""
    store = CandleStore("test", base_dir=tmp_path)
    end = START_MS + 60 * DAY_MS
    store.save(SYMBOL, "1h", synth_candles(3_600_000, START_MS, end))
    store.save(SYMBOL, "4h", synth_candles(14_400_000, START_MS, end))

    # velas 5m planas y, el día del test a las 07:05 UTC, una vela roja enorme:
    # abre en 100.5, marca high 102 (antes del fill) y cae a 97 cerrando en 97.5
    mgmt = synth_candles(300_000, START_MS, end, p0=100.0, slope_per_day=0.0)
    mgmt.loc[:, ["open", "high", "low", "close"]] = 100.0
    mgmt["high"], mgmt["low"] = 100.05, 99.95
    day_ts = START_MS + 40 * DAY_MS + int(7.083 * 3_600_000)  # 2026-02-10 ~07:05 UTC
    idx = mgmt.index[mgmt["timestamp"] == mgmt.loc[(mgmt["timestamp"] - day_ts).abs().idxmin(), "timestamp"]][0]
    mgmt.loc[idx, ["open", "high", "low", "close"]] = [100.5, 102.0, 97.0, 97.5]
    store.save(SYMBOL, "5m", mgmt)

    config = _config(mode="pullback_limit", pullback_pct=1.0, timeout_hours=6, on_timeout="cancel")
    config.steps.basis = "price"
    config.steps.step_pct = 2.0  # escalón en ~100.98: solo alcanzable por el high pre-fill (102)
    config.stop.atr_mult = 10   # SL muy lejos: aísla el exploit del escalón

    result = BacktestEngine(config, store=store).run(date(2026, 2, 10), date(2026, 2, 10))

    assert result.metrics["entry_filled"] == 1
    trade = result.trades[0]
    # Con el bug, el high 102 (previo al fill) disparaba un 'step' en ~100.5 en la
    # misma vela del fill. Corregido: esa vela solo se evalúa con su close (97.5),
    # que ni toca escalón ni SL; el resto del día es plano -> solo open + cierre 'end'.
    assert [f.kind for f in trade.fills] == ["open", "end"]
    assert trade.steps_hit == 0


def test_pullback_timeout_market_entra_igualmente(tmp_path):
    store = _store_with_synth(tmp_path)
    config = _config(mode="pullback_limit", pullback_pct=30.0, timeout_hours=4, on_timeout="market")
    result = BacktestEngine(config, store=store).run(date(2026, 2, 10), date(2026, 2, 14))

    m = result.metrics
    assert m["entry_timeout_market"] == m["entry_orders"] > 0
    assert m["num_trades"] == m["entry_timeout_market"]
    # las entradas por timeout son a mercado: pagan taker
    for t in result.trades:
        fee_pct = t.fills[0].fee / (t.size * t.entry_price) * 100
        assert fee_pct == pytest.approx(0.05)
