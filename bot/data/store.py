"""Cache local de velas en Parquet: data/candles/<exchange>/<símbolo>_<tf>.parquet.

El backtest lee siempre de aquí; `python -m bot fetch` descarga/actualiza.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from bot.config import DATA_DIR
from bot.data.exchange import Exchange, TIMEFRAME_MS


def _safe_symbol(symbol: str) -> str:
    return symbol.replace("/", "-").replace(":", "_")


class CandleStore:
    def __init__(self, exchange_id: str = "okx", base_dir: Path | None = None):
        self.exchange_id = exchange_id
        self.dir = Path(base_dir) if base_dir else DATA_DIR / "candles" / exchange_id
        self.dir.mkdir(parents=True, exist_ok=True)

    def path(self, symbol: str, timeframe: str) -> Path:
        return self.dir / f"{_safe_symbol(symbol)}_{timeframe}.parquet"

    def load(self, symbol: str, timeframe: str) -> pd.DataFrame:
        p = self.path(symbol, timeframe)
        if not p.exists():
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        return pd.read_parquet(p)

    def save(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        df.to_parquet(self.path(symbol, timeframe), index=False)

    def update(
        self, exchange: Exchange, symbol: str, timeframe: str, since_ms: int, until_ms: int
    ) -> pd.DataFrame:
        """Completa la cache para cubrir [since_ms, until_ms) y la devuelve."""
        existing = self.load(symbol, timeframe)
        step = TIMEFRAME_MS[timeframe]
        frames = [existing]
        if existing.empty:
            frames.append(exchange.fetch_ohlcv(symbol, timeframe, since_ms, until_ms))
        else:
            first, last = int(existing["timestamp"].min()), int(existing["timestamp"].max())
            if since_ms < first:
                frames.append(exchange.fetch_ohlcv(symbol, timeframe, since_ms, first))
            if until_ms > last + step:
                frames.append(exchange.fetch_ohlcv(symbol, timeframe, last + step, until_ms))
        df = pd.concat(frames, ignore_index=True)
        df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
        self.save(symbol, timeframe, df)
        return df

    def slice(self, symbol: str, timeframe: str, since_ms: int, until_ms: int) -> pd.DataFrame:
        df = self.load(symbol, timeframe)
        out = df[(df["timestamp"] >= since_ms) & (df["timestamp"] < until_ms)]
        return out.reset_index(drop=True)
