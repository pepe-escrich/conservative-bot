"""Runtime del bot en tiempo real, con dos modos de ejecución:

- paper: fills simulados internamente (sin cuenta, precios públicos de ccxt).
- okx: órdenes reales contra la cuenta OKX (demo o real) vía python-okx.

En ambos casos: a la hora programada puntúa el catálogo y abre los top-N
(a mercado o con limitada en pullback según config); un bucle de polling
alimenta el manager de escalones. Todo el estado vive en SQLite y los trades
abiertos se recuperan al reiniciar.

El % de capital por trade y el estado arrancado/parado se controlan desde la
web (tabla bot_state).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from bot.config import BotConfig, with_overrides
from bot.data.exchange import Exchange
from bot.data.store import CandleStore
from bot.indicators.base import SignalContext
from bot.indicators.classic import atr as atr_series
from bot.persistence.db import Database
from bot.scoring.scorer import rank_tokens, score_token
from bot.strategy.manager import StepLadderManager
from bot.strategy.models import OPEN, PendingEntry, Trade
from bot.strategy.setup import build_trade, side_from_score, trade_from_execution

log = logging.getLogger("bot")

DAY_MS = 86_400_000


class BotRunner:
    def __init__(self, config: BotConfig, db: Database | None = None):
        self.config = config
        self.db = db or Database()
        self.exchange = Exchange(config.exchange)
        self.store = CandleStore(config.exchange)
        self.tz = ZoneInfo(config.schedule.timezone)
        self.live = config.execution.mode == "okx"
        self.broker = None
        if self.live:
            from bot.engine.live_manager import LiveLadderManager
            from bot.engine.okx_broker import OKXBroker

            self.broker = OKXBroker(config)
            self.broker.ensure_net_mode()
            self.manager: StepLadderManager = LiveLadderManager(config, self.broker)
        else:
            self.manager = StepLadderManager(config)
        self.open_trades: list[Trade] = []
        # órdenes de entrada pendientes (pullback). En paper solo en memoria;
        # en okx son órdenes reales en el exchange (expiran por timeout).
        self.pending: list[PendingEntry] = []
        self._stop = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self.scheduler = BackgroundScheduler(timezone=str(self.tz))

    # ------------------------------------------------------------------
    # Configuración efectiva y equity
    # ------------------------------------------------------------------

    @property
    def effective_config(self) -> BotConfig:
        """Config con el % de capital por trade fijado al iniciar el bot desde la web."""
        fraction = self.db.get_state("capital_fraction_pct")
        if fraction:
            return with_overrides(
                self.config,
                {"sizing": {"mode": "capital_fraction", "capital_fraction_pct": float(fraction)}},
            )
        return self.config

    def equity(self) -> float:
        """Equity para el sizing: saldo real de la cuenta (okx) o contable (paper)."""
        if self.live:
            return self.broker.balance()["total_eq_usd"]
        baseline = self.db.baseline_ms()
        reference = float(self.db.get_state("reference_capital", str(self.config.capital_inicial)))
        return reference + self.db.total_realized_pnl("paper", since_ms=baseline)

    def _last_prices(self, symbols: list[str]) -> dict[str, float]:
        if self.live:
            return self.broker.last_prices(symbols)
        return self.exchange.fetch_last_prices(symbols)

    # ------------------------------------------------------------------

    def start(self) -> None:
        self.open_trades = self.db.load_open_trades("paper")
        log.info("bot: %d trades abiertos recuperados (modo %s)", len(self.open_trades), self.config.execution.mode)
        self.scheduler.add_job(
            self.daily_job,
            CronTrigger(hour=self.config.schedule.hour, minute=self.config.schedule.minute),
            id="daily_open",
        )
        self.scheduler.start()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True, name="bot-poll")
        self._poll_thread.start()
        log.info("bot: arrancado (job diario a las %s)", self.config.schedule.time)

    def stop(self, close_positions: bool = False) -> int:
        """Para el bot. Si close_positions, cierra los trades abiertos y cancela pendientes."""
        self._stop.set()
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        closed = 0
        if close_positions:
            closed = self.close_all("manual")
        return closed

    def close_all(self, reason: str = "manual") -> int:
        now_ms = int(time.time() * 1000)
        for p in list(self.pending):
            if self.live and p.order_id:
                self.broker.cancel_order(p.symbol, p.order_id)
            self.pending.remove(p)
        prices = self._last_prices(sorted({t.symbol for t in self.open_trades})) if self.open_trades else {}
        closed = 0
        for trade in list(self.open_trades):
            price = prices.get(trade.symbol, trade.entry_price)
            self.manager.force_close(trade, now_ms, price, kind=reason)
            self.db.save_trade(trade)
            self.open_trades.remove(trade)
            closed += 1
        if closed:
            self.db.add_equity_snapshot("paper", now_ms, self.equity())
        return closed

    # ------------------------------------------------------------------
    # Job diario: scoring y entradas
    # ------------------------------------------------------------------

    def daily_job(self) -> None:
        cfg = self.effective_config
        now_ms = int(time.time() * 1000)
        log.info("bot: job diario, actualizando velas y puntuando %d tokens", len(cfg.universe))

        scores = []
        atrs: dict[str, float] = {}
        for symbol in cfg.universe:
            try:
                signal_df = self.store.update(
                    self.exchange, symbol, cfg.timeframes.signal, now_ms - 45 * DAY_MS, now_ms
                )
                trend_df = self.store.update(
                    self.exchange, symbol, cfg.timeframes.trend, now_ms - 120 * DAY_MS, now_ms
                )
            except Exception as e:  # un símbolo caído no aborta el día
                log.warning("bot: error descargando %s: %s", symbol, e)
                continue
            if len(signal_df) < 50 or len(trend_df) < 50:
                continue
            ctx = SignalContext(signal_df=signal_df.tail(500), trend_df=trend_df.tail(400), config=cfg)
            scores.append(score_token(symbol, ctx))
            atrs[symbol] = float(atr_series(signal_df.tail(500), cfg.stop.atr_period).iloc[-1])

        busy = {t.symbol for t in self.open_trades} | {p.symbol for p in self.pending}
        candidates = [s for s in rank_tokens(scores, cfg) if s.symbol not in busy]
        prices = self._last_prices([c.symbol for c in candidates]) if candidates else {}

        opened = set()
        for cand in candidates:
            price = prices.get(cand.symbol)
            if not price or cand.symbol not in atrs:
                continue
            try:
                if self._enter(cfg, cand.symbol, side_from_score(cand.score), price, atrs[cand.symbol], cand.score, now_ms):
                    opened.add(cand.symbol)
            except Exception as e:
                log.error("bot: error abriendo %s: %s", cand.symbol, e)

        today = datetime.now(self.tz).date().isoformat()
        self.db.save_scores("paper", today, scores, opened)
        self.db.add_equity_snapshot("paper", now_ms, self.equity())

    def _sized_trade(self, cfg: BotConfig, symbol: str, side: int, price: float, atr_value: float, score: float, now_ms: int) -> Trade | None:
        """Calcula tamaño y niveles (sin ejecutar): plantilla para la orden real."""
        equity = self.equity()
        reserved = sum(t.margin * (t.remaining_size / t.size) for t in self.open_trades)
        return build_trade(
            symbol, side, now_ms, price, pd.DataFrame(),
            equity=equity, available_margin=max(equity - reserved, 0.0),
            config=cfg, score=score, mode="paper", atr_value=atr_value,
        )

    def _enter(self, cfg, symbol: str, side: int, price: float, atr_value: float, score: float, now_ms: int) -> bool:
        template = self._sized_trade(cfg, symbol, side, price, atr_value, score, now_ms)
        if template is None:
            return False

        if cfg.entry.mode == "pullback_limit":
            limit_price = price * (1 - side * cfg.entry.pullback_pct / 100)
            order_id = None
            if self.live:
                order_id = self.broker.limit_order(symbol, "buy" if side > 0 else "sell", template.size, limit_price)
            self.pending.append(
                PendingEntry(
                    symbol=symbol, side=side, limit_price=limit_price, created=now_ms,
                    expires=now_ms + int(cfg.entry.timeout_hours * 3_600_000),
                    score=score, atr_value=atr_value, signal_price=price,
                    order_id=order_id, size=template.size,
                )
            )
            log.info("bot: limitada %s %s @ %.6g (señal %.6g)", "long" if side > 0 else "short", symbol, limit_price, price)
            return True

        if self.live:
            result = self.broker.market_order(symbol, "buy" if side > 0 else "sell", template.size)
            trade = trade_from_execution(
                symbol, side, result.price, result.size, result.fee, result.time, atr_value, cfg, score
            )
        else:
            trade = template
        self.db.save_trade(trade)
        self.open_trades.append(trade)
        log.info("bot: abierto %s %s @ %.6g (score %.3f)", trade.side_name, symbol, trade.entry_price, score)
        return True

    # ------------------------------------------------------------------
    # Polling: gestión de trades y de órdenes pendientes
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        while not self._stop.wait(self.config.paper.poll_seconds):
            if not self.open_trades and not self.pending:
                continue
            try:
                self.poll_once()
            except Exception as e:
                log.warning("bot: error en polling: %s", e)

    def poll_once(self) -> None:
        symbols = sorted({t.symbol for t in self.open_trades} | {p.symbol for p in self.pending})
        prices = self._last_prices(symbols)
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
                self.db.add_equity_snapshot("paper", now_ms, self.equity())
                log.info("bot: cerrado %s (%s) pnl %.2f", trade.symbol, trade.close_reason, trade.realized_pnl)

    def _register_entry_fill(self, p: PendingEntry, price: float, size: float, fee: float, ts: int, cfg: BotConfig) -> None:
        trade = trade_from_execution(p.symbol, p.side, price, size, fee, ts, p.atr_value, cfg, p.score)
        self.db.save_trade(trade)
        self.open_trades.append(trade)
        log.info("bot: fill de entrada %s %s @ %.6g", trade.side_name, p.symbol, price)

    def _process_pending(self, prices: dict[str, float], now_ms: int) -> None:
        cfg = self.effective_config
        for p in list(self.pending):
            expired = now_ms >= p.expires

            if self.live and p.order_id:
                # orden limitada real: consultar su estado en OKX
                state, result = self.broker.order_status(p.symbol, p.order_id)
                if state == "filled":
                    self.pending.remove(p)
                    self._register_entry_fill(p, result.price, result.size, result.fee, result.time, cfg)
                    continue
                if state == "canceled":
                    self.pending.remove(p)
                    continue
                if expired:
                    self.pending.remove(p)
                    self.broker.cancel_order(p.symbol, p.order_id)
                    if cfg.entry.on_timeout == "market":
                        result = self.broker.market_order(p.symbol, "buy" if p.side > 0 else "sell", p.size)
                        self._register_entry_fill(p, result.price, result.size, result.fee, result.time, cfg)
                continue

            # modo paper: simular el fill de la limitada con el último precio
            price = prices.get(p.symbol)
            if not price:
                continue
            crossed = price <= p.limit_price if p.side > 0 else price >= p.limit_price
            if not crossed and not expired:
                continue
            self.pending.remove(p)
            if not crossed and cfg.entry.on_timeout == "cancel":
                log.info("bot: limitada %s cancelada por timeout", p.symbol)
                continue
            entry_type = "limit" if crossed else "market"
            fill_price = (min(price, p.limit_price) if p.side > 0 else max(price, p.limit_price)) if crossed else price
            equity = self.equity()
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
            log.info("bot: %s %s %s @ %.6g", "fill limitada" if crossed else "timeout->market",
                     trade.side_name, trade.symbol, trade.entry_price)


# Compatibilidad con el nombre anterior
PaperRunner = BotRunner
