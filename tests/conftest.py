import pytest

from bot.config import BotConfig


@pytest.fixture
def config() -> BotConfig:
    """Config de test: sin comisiones ni slippage para aritmética exacta."""
    return BotConfig(
        universe=["BTC/USDT:USDT"],
        leverage=10,
        capital_inicial=1000,
        risk_per_trade_pct=1.0,
        risk_reward=3,
        steps={"basis": "price", "step_pct": 1.0, "partial_close_pct": 50, "trail_mode": "previous_step"},
        fees={"taker_pct": 0.0, "slippage_pct": 0.0},
    )
