"""Smoke test del estudio de optimización: plumbing completo con pocos trials."""

from datetime import date

from bot.backtest.optimize import run_study
from bot.config import BotConfig
from bot.data.store import CandleStore
from tests.test_backtest import DAY_MS, START_MS, SYMBOL, synth_candles


def test_run_study_smoke(tmp_path):
    store = CandleStore("test", base_dir=tmp_path)
    end = START_MS + 60 * DAY_MS
    store.save(SYMBOL, "1h", synth_candles(3_600_000, START_MS, end))
    store.save(SYMBOL, "4h", synth_candles(14_400_000, START_MS, end))
    store.save(SYMBOL, "5m", synth_candles(300_000, START_MS, end))

    config = BotConfig(
        universe=[SYMBOL],
        min_score=0.0,
        capital_inicial=1000,
        fees={"taker_pct": 0.05, "slippage_pct": 0.0},
    )
    result = run_study(
        config, date(2026, 2, 10), date(2026, 2, 24), n_trials=5, split=0.6, seed=1, store=store
    )

    assert result.report_path.exists()
    assert "steps" in result.recommended_overrides
    assert "indicators" in result.recommended_overrides
    assert len(result.study.trials) == 5
    # IS y OOS no se solapan
    assert result.is_range[1] < result.oos_range[0]
