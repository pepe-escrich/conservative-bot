"""Test de integración del motor de backtest con datos sintéticos en cache."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from bot.backtest.engine import BacktestEngine
from bot.config import BotConfig
from bot.data.store import CandleStore

DAY_MS = 86_400_000
START_MS = 1_767_225_600_000  # 2026-01-01 00:00 UTC
SYMBOL = "BTC/USDT:USDT"


def synth_candles(tf_ms: int, start_ms: int, end_ms: int, p0=100.0, slope_per_day=0.5):
    ts = np.arange(start_ms, end_ms, tf_ms)
    base = p0 + slope_per_day * (ts - start_ms) / DAY_MS
    wiggle = 0.004 * base * np.sin(np.arange(len(ts)) / 7)  # oscilación intradía
    close = base + wiggle
    open_ = np.roll(close, 1)
    open_[0] = p0
    hi = np.maximum(open_, close) * 1.003
    lo = np.minimum(open_, close) * 0.997
    return pd.DataFrame(
        {"timestamp": ts, "open": open_, "high": hi, "low": lo, "close": close,
         "volume": np.full(len(ts), 1000.0)}
    )


@pytest.fixture
def store(tmp_path):
    s = CandleStore("test", base_dir=tmp_path)
    end = START_MS + 60 * DAY_MS
    s.save(SYMBOL, "1h", synth_candles(3_600_000, START_MS, end))
    s.save(SYMBOL, "4h", synth_candles(14_400_000, START_MS, end))
    s.save(SYMBOL, "5m", synth_candles(300_000, START_MS, end))
    return s


def test_backtest_end_to_end(store):
    config = BotConfig(
        universe=[SYMBOL],
        min_score=0.0,           # que siempre seleccione al único símbolo
        trades_per_day=3,
        capital_inicial=1000,
        fees={"taker_pct": 0.05, "slippage_pct": 0.0},
        timeframes={"signal": "1h", "trend": "4h", "management": "5m"},
    )
    engine = BacktestEngine(config, store=store)
    result = engine.run(date_from=date(2026, 2, 10), date_to=date(2026, 2, 20))

    assert len(result.trades) >= 5
    assert all(t.status == "closed" for t in result.trades)

    # invariante contable: la variación de equity es la suma de PnL netos
    total_pnl = sum(t.realized_pnl for t in result.trades)
    final_equity = result.equity_curve[-1][1]
    assert final_equity - config.capital_inicial == pytest.approx(total_pnl, abs=1e-6)

    m = result.metrics
    assert m["num_trades"] == len(result.trades)
    assert m["final_equity"] == pytest.approx(final_equity, abs=0.01)
    assert 0 <= m["win_rate_pct"] <= 100
    assert m["total_fees"] > 0

    # sin lookahead: ningún fill es anterior a la entrada de su trade
    for t in result.trades:
        assert all(f.time >= t.entry_time for f in t.fills)
