"""Carga y validación de la configuración del bot (config/config.yaml)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
DATA_DIR = Path(os.environ.get("BOT_DATA_DIR", PROJECT_ROOT / "data"))


class ScheduleConfig(BaseModel):
    time: str = "07:00"
    timezone: str = "Europe/Madrid"

    @field_validator("time")
    @classmethod
    def _valid_time(cls, v: str) -> str:
        h, m = v.split(":")
        assert 0 <= int(h) < 24 and 0 <= int(m) < 60
        return v

    @property
    def hour(self) -> int:
        return int(self.time.split(":")[0])

    @property
    def minute(self) -> int:
        return int(self.time.split(":")[1])


class StopConfig(BaseModel):
    atr_mult: float = 1.5
    atr_period: int = 14


class StepsConfig(BaseModel):
    basis: Literal["margin_pnl", "price"] = "margin_pnl"
    step_pct: float = 1.0
    partial_close_pct: float = 50.0
    trail_mode: Literal["previous_step", "breakeven_only"] = "previous_step"


class FeesConfig(BaseModel):
    taker_pct: float = 0.05
    slippage_pct: float = 0.02


class TimeframesConfig(BaseModel):
    signal: str = "1h"
    trend: str = "4h"
    management: str = "5m"


class FrvpConfig(BaseModel):
    lookback_days: int = 14
    value_area_pct: float = 70.0
    bins: int = 100


class PaperConfig(BaseModel):
    enabled: bool = False
    poll_seconds: int = 15


class SizingConfig(BaseModel):
    # 'risk': el tamaño se calcula para perder risk_per_trade_pct% del equity si salta el SL.
    # 'capital_fraction': cada trade usa un % fijo del capital (al inicio del día) como margen.
    mode: Literal["risk", "capital_fraction"] = "risk"
    capital_fraction_pct: float = 10.0


class BotConfig(BaseModel):
    exchange: str = "okx"
    universe: list[str] = Field(default_factory=list)
    schedule: ScheduleConfig = ScheduleConfig()
    trades_per_day: int = 3
    min_score: float = 0.3
    leverage: float = 10
    capital_inicial: float = 1000
    risk_per_trade_pct: float = 1.0
    sizing: SizingConfig = SizingConfig()
    risk_reward: float = 3
    stop: StopConfig = StopConfig()
    steps: StepsConfig = StepsConfig()
    fees: FeesConfig = FeesConfig()
    indicators: dict[str, float] = Field(
        default_factory=lambda: {
            "ema_trend": 0.25,
            "rsi": 0.15,
            "macd": 0.15,
            "adx": 0.10,
            "bollinger": 0.10,
            "frvp": 0.25,
        }
    )
    timeframes: TimeframesConfig = TimeframesConfig()
    frvp: FrvpConfig = FrvpConfig()
    paper: PaperConfig = PaperConfig()


def load_config(path: str | Path | None = None) -> BotConfig:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(cfg_path) as f:
        raw = yaml.safe_load(f) or {}
    return BotConfig(**raw)


def deep_merge(base: dict, overrides: dict) -> dict:
    """Fusión recursiva de dicts: overrides gana; los sub-dicts se combinan."""
    out = dict(base)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def with_overrides(config: BotConfig, overrides: dict) -> BotConfig:
    return BotConfig(**deep_merge(config.model_dump(), overrides))
