"""Paper trading en tiempo real.

- A la hora programada (07:00 por defecto): actualiza velas, puntúa el catálogo
  y abre los top-N trades al precio de mercado actual.
- Un bucle de polling (~15s) consulta los últimos precios y alimenta el mismo
  StepLadderManager que usa el backtest (escalones, trailing, SL, TP).
- Todo el estado vive en SQLite: al reiniciar el proceso se reanudan los
  trades abiertos.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from bot.config import BotConfig
from bot.data.exchange import Exchange
from bot.data.store import CandleStore
from bot.indicators.base import SignalContext
from bot.persistence.db import Database
from bot.scoring.scorer import rank_tokens, score_token
from bot.indicators.classic import atr as atr_series
from bot.strategy.manager import StepLadderManager
from bot.strategy.models import OPEN, PendingEntry, Trade
from bot.strategy.setup import build_trade, side_from_score

log = logging.getLogger("paper")

DAY_MS = 86_400_000


class PaperRunner:
    def __init__(self, config: BotConfig, db: Database | None = None):
        self.config = config
        self.db = db or Database()
        self.exchange = Exchange(config.exchange)
        self.store = CandleStore(config.exchange)
        self.manager = StepLadderManager(config)
        self.tz = ZoneInfo(config.schedule.timezone)
        self.open_trades: list[Trade] = []
        # órdenes limitadas pendientes (modo pullback). Solo en memoria: si el
        # proceso se reinicia se pierden, pero expiran en horas por diseño.
        self.pending: list[PendingEntry] = []
        self._stop = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self.scheduler = BackgroundScheduler(timezone=str(self.tz))

    # ------------------------------------------------------------------

    @property
    def equity(self) -> float:
        return self.config.capital_inicial + self.db.total_realized_pnl("paper")

    def start(self) -> None:
        self.open_trades = self.db.load_open_trades("paper")
        log.info("paper: %d trades abiertos recuperados", len(self.open_trades))
        self.scheduler.add_job(
            self.daily_job,
            CronTrigger(hour=self.config.schedule.hour, minute=self.config.schedule.minute),
            id="daily_open",
        )
        self.scheduler.start()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True, name="paper-poll")
        self._poll_thread.start()
        log.info("paper: runner arrancado (job diario a las %s)", self.config.schedule.time)

    def stop(self) -> None:
        self._stop.set()
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    # ------------------------------------------------------------------

    def daily_job(self) -> None:
        """Scoring y apertura de los trades del día."""
        cfg = self.config
        now_ms = int(time.time() * 1000)
        log.info("paper: job diario, actualizando velas y puntuando %d tokens", len(cfg.universe))

        scores = []
        frames_by_symbol = {}
        for symbol in cfg.universe:
            try:
                signal_df = self.store.update(
                    self.exchange, symbol, cfg.timeframes.signal, now_ms - 45 * DAY_MS, now_ms
                )
                trend_df = self.store.update(
                    self.exchange, symbol, cfg.timeframes.trend, now_ms - 120 * DAY_MS, now_ms
                )
            except Exception as e:  # símbolo puntual caído no aborta el día
                log.warning("paper: error descargando %s: %s", symbol, e)
                continue
            if len(signal_df) < 50 or len(trend_df) < 50:
                continue
            frames_by_symbol[symbol] = signal_df
            ctx = SignalContext(signal_df=signal_df.tail(500), trend_df=trend_df.tail(400), config=cfg)
            scores.append(score_token(symbol, ctx))

        busy = {t.symbol for t in self.open_trades} | {p.symbol for p in self.pending}
        candidates = [s for s in rank_tokens(scores, cfg) if s.symbol not in busy]
        prices = self.exchange.fetch_last_prices([c.symbol for c in candidates]) if candidates else {}

        opened = set()
        for cand in candidates:
            price = prices.get(cand.symbol)
            if not price:
                continue
            side = side_from_score(cand.score)
            signal_df = frames_by_symbol[cand.symbol].tail(500)
            if cfg.entry.mode == "pullback_limit":
                if len(signal_df) < cfg.stop.atr_period + 5:
                    continue
                pending = PendingEntry(
                    symbol=cand.symbol,
                    side=side,
                    limit_price=price * (1 - side * cfg.entry.pullback_pct / 100),
                    created=now_ms,
                    expires=now_ms + int(cfg.entry.timeout_hours * 3_600_000),
                    score=cand.score,
                    atr_value=float(atr_series(signal_df, cfg.stop.atr_period).iloc[-1]),
                    signal_price=price,
                )
                self.pending.append(pending)
                opened.add(cand.symbol)
                log.info(
                    "paper: limitada %s %s @ %.6g (precio %.6g, score %.3f)",
                    "long" if side > 0 else "short", cand.symbol, pending.limit_price, price, cand.score,
                )
                continue
            equity = self.equity
            reserved = sum(t.margin * (t.remaining_size / t.size) for t in self.open_trades)
            trade = build_trade(
                cand.symbol,
                side,
                now_ms,
                price,
                signal_df,
                equity=equity,
                available_margin=max(equity - reserved, 0.0),
                config=cfg,
                score=cand.score,
                mode="paper",
            )
            if trade is None:
                continue
            self.db.save_trade(trade)
            self.open_trades.append(trade)
            opened.add(cand.symbol)
            log.info("paper: abierto %s %s @ %.6g (score %.3f)", trade.side_name, trade.symbol, trade.entry_price, cand.score)

        today = datetime.now(self.tz).date().isoformat()
        self.db.save_scores("paper", today, scores, opened)
        self.db.add_equity_snapshot("paper", now_ms, self.equity)

    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        while not self._stop.wait(self.config.paper.poll_seconds):
            if not self.open_trades and not self.pending:
                continue
            try:
                self.poll_once()
            except Exception as e:
                log.warning("paper: error en polling: %s", e)

    def poll_once(self) -> None:
        symbols = sorted({t.symbol for t in self.open_trades} | {p.symbol for p in self.pending})
        prices = self.exchange.fetch_last_prices(symbols)
        now_ms = int(time.time() * 1000)
        self.db.upsert_prices(prices, now_ms)
        self._process_pending(prices, now_ms)

        for trade in list(self.open_trades):
            price = prices.get(trade.symbol)
            if not price:
                continue
            fills = self.manager.on_tick(trade, now_ms, price)
            if fills:
                self.db.save_trade(trade)
            if trade.status != OPEN:
                self.open_trades.remove(trade)
                self.db.add_equity_snapshot("paper", now_ms, self.equity)
                log.info(
                    "paper: cerrado %s (%s) pnl %.2f", trade.symbol, trade.close_reason, trade.realized_pnl
                )

    def _process_pending(self, prices: dict[str, float], now_ms: int) -> None:
        """Fills y expiraciones de las órdenes limitadas (modo pullback)."""
        cfg = self.config
        for p in list(self.pending):
            price = prices.get(p.symbol)
            if not price:
                continue
            crossed = price <= p.limit_price if p.side > 0 else price >= p.limit_price
            expired = now_ms >= p.expires
            if not crossed and not expired:
                continue
            self.pending.remove(p)
            if not crossed and cfg.entry.on_timeout == "cancel":
                log.info("paper: limitada %s cancelada por timeout", p.symbol)
                continue
            # fill de la limitada (a su precio o mejor) o entrada a mercado al expirar
            entry_type = "limit" if crossed else "market"
            fill_price = (min(price, p.limit_price) if p.side > 0 else max(price, p.limit_price)) if crossed else price
            equity = self.equity
            reserved = sum(t.margin * (t.remaining_size / t.size) for t in self.open_trades)
            trade = build_trade(
                p.symbol, p.side, now_ms, fill_price,
                self.store.load(p.symbol, cfg.timeframes.signal).tail(500),
                equity=equity, available_margin=max(equity - reserved, 0.0),
                config=cfg, score=p.score, mode="paper",
                atr_value=p.atr_value, entry_type=entry_type,
            )
            if trade is None:
                continue
            self.db.save_trade(trade)
            self.open_trades.append(trade)
            log.info(
                "paper: %s %s %s @ %.6g", "fill limitada" if crossed else "timeout->market",
                trade.side_name, trade.symbol, trade.entry_price,
            )
