"""Acceso a mercado vía ccxt. Agnóstico de exchange (OKX por defecto).

Solo usa endpoints públicos: OHLCV y tickers. No requiere API keys.
"""

from __future__ import annotations

import random
import time

import ccxt
import pandas as pd

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


class Exchange:
    def __init__(self, exchange_id: str = "okx"):
        klass = getattr(ccxt, exchange_id)
        self.client = klass({"enableRateLimit": True})
        self.id = exchange_id

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, since_ms: int, until_ms: int | None = None
    ) -> pd.DataFrame:
        """Descarga OHLCV paginado entre since_ms y until_ms (UTC, ms)."""
        until_ms = until_ms or int(time.time() * 1000)
        step = TIMEFRAME_MS[timeframe]
        rows: list[list] = []
        cursor = since_ms
        # ante un batch vacío (p. ej. rango anterior al listado del token) se salta
        # hacia delante en lugar de abortar; como mucho se pierden JUMP de las
        # primeras velas del listado, irrelevantes (el scoring exige historial).
        jump = max(step * 100, 15 * 86_400_000)
        while cursor < until_ms:
            batch = self._fetch_with_retry(symbol, timeframe, cursor)
            if not batch:
                cursor += jump
                continue
            rows.extend(batch)
            last = batch[-1][0]
            if last <= cursor:
                break
            cursor = last + step
        df = pd.DataFrame(rows, columns=OHLCV_COLUMNS)
        df = df[(df["timestamp"] >= since_ms) & (df["timestamp"] < until_ms)]
        df = df.drop_duplicates(subset="timestamp").sort_values("timestamp")
        return df.reset_index(drop=True)

    def _fetch_with_retry(self, symbol: str, timeframe: str, since: int, attempts: int = 6) -> list[list]:
        """fetch_ohlcv con backoff exponencial ante rate limits o cortes de red."""
        for attempt in range(attempts):
            try:
                return self.client.fetch_ohlcv(symbol, timeframe, since=since, limit=100)
            except (ccxt.NetworkError, ccxt.RateLimitExceeded):
                if attempt == attempts - 1:
                    raise
                time.sleep(2**attempt + random.random())
        return []

    def fetch_last_prices(self, symbols: list[str]) -> dict[str, float]:
        """Último precio de cada símbolo (para paper trading)."""
        tickers = self.client.fetch_tickers(symbols)
        return {s: t["last"] for s, t in tickers.items() if t.get("last")}
