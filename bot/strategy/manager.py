"""Manager de escalones: la gestión del trade una vez abierto.

Reglas:
- Cada vez que el beneficio alcanza el escalón k (k * step_pct, medido en
  % de PnL sobre margen o % de precio según `steps.basis`):
    * se cierra `partial_close_pct`% de la posición restante
    * el SL se mueve: 1er escalón -> breakeven; siguientes -> precio del
      escalón anterior (trail_mode=previous_step) o se queda en breakeven.
- El trade termina al tocar el SL vigente, el TP (RR:1) o agotar la posición.

La misma clase gestiona velas (backtest) y ticks (paper). Resolución
intra-vela conservadora: si el SL y un escalón caben en la misma vela, se
asume que el SL se toca primero.
"""

from __future__ import annotations

from bot.config import BotConfig
from bot.strategy.models import CLOSED, OPEN, Fill, Trade

# Si tras un parcial quedaría menos del 5% del tamaño original, se cierra todo:
# evita posiciones residuales infinitamente pequeñas (mitades sucesivas).
MIN_REMAINING_FRACTION = 0.05


class StepLadderManager:
    def __init__(self, config: BotConfig):
        self.steps = config.steps
        self.fees = config.fees

    # ------------------------------------------------------------------
    # Niveles
    # ------------------------------------------------------------------

    def step_price(self, trade: Trade, k: int) -> float:
        """Precio al que el beneficio alcanza el escalón k."""
        pct = k * self.steps.step_pct / 100
        if self.steps.basis == "margin_pnl":
            pct /= trade.leverage
        return trade.entry_price * (1 + trade.side * pct)

    def _trailed_sl(self, trade: Trade) -> float:
        if trade.steps_hit <= 1 or self.steps.trail_mode == "breakeven_only":
            return trade.entry_price  # breakeven
        return self.step_price(trade, trade.steps_hit - 1)

    def _stop_kind(self, trade: Trade) -> str:
        if trade.side * (trade.current_sl - trade.entry_price) > 1e-12:
            return "trail"
        if abs(trade.current_sl - trade.entry_price) <= 1e-12 * trade.entry_price:
            return "be"
        return "sl"

    # ------------------------------------------------------------------
    # Ejecución de fills
    # ------------------------------------------------------------------

    def _executed(self, trade: Trade, price: float) -> float:
        """Precio ejecutado de un cierre: slippage en contra."""
        return price * (1 - trade.side * self.fees.slippage_pct / 100)

    def _fill_close(self, trade: Trade, ts: int, price: float, qty: float, kind: str) -> Fill:
        executed = self._executed(trade, price)
        gross = trade.side * (executed - trade.entry_price) * qty
        fee = executed * qty * self.fees.taker_pct / 100
        fill = Fill(time=ts, price=executed, size=qty, kind=kind, pnl=gross, fee=fee)
        trade.fills.append(fill)
        trade.remaining_size -= qty
        trade.realized_pnl += gross - fee
        trade.fees_paid += fee
        return fill

    def _close_all(self, trade: Trade, ts: int, price: float, kind: str) -> Fill:
        fill = self._fill_close(trade, ts, price, trade.remaining_size, kind)
        trade.status = CLOSED
        trade.close_time = ts
        trade.close_reason = kind
        return fill

    def _partial(self, trade: Trade, ts: int, price: float, k: int) -> Fill:
        qty = trade.remaining_size * self.steps.partial_close_pct / 100
        if trade.remaining_size - qty < MIN_REMAINING_FRACTION * trade.size:
            return self._close_all(trade, ts, price, "ladder")
        fill = self._fill_close(trade, ts, price, qty, "step")
        trade.steps_hit = k
        trade.current_sl = self._trailed_sl(trade)
        return fill

    # ------------------------------------------------------------------
    # Eventos de mercado
    # ------------------------------------------------------------------

    def on_candle(self, trade: Trade, ts: int, o: float, h: float, l: float, c: float) -> list[Fill]:
        """Procesa una vela OHLC. Devuelve los fills generados."""
        fills: list[Fill] = []
        if trade.status != OPEN:
            return fills
        side = trade.side

        # 1) SL primero (conservador). Si hay gap contra la posición, se ejecuta al open.
        adverse = l if side > 0 else h
        if side * (adverse - trade.current_sl) <= 0:
            stop_fill_price = min(trade.current_sl, o) if side > 0 else max(trade.current_sl, o)
            fills.append(self._close_all(trade, ts, stop_fill_price, self._stop_kind(trade)))
            return fills

        # 2) Escalones y TP por el extremo favorable, en orden de precio.
        favorable = h if side > 0 else l
        while trade.status == OPEN:
            sp = self.step_price(trade, trade.steps_hit + 1)
            step_hit = side * (favorable - sp) >= 0
            tp_hit = side * (favorable - trade.tp) >= 0
            step_before_tp = side * (sp - trade.tp) < 0
            if step_hit and step_before_tp:
                fill_price = max(sp, o) if side > 0 else min(sp, o)
                fills.append(self._partial(trade, ts, fill_price, trade.steps_hit + 1))
            elif tp_hit:
                fill_price = max(trade.tp, o) if side > 0 else min(trade.tp, o)
                fills.append(self._close_all(trade, ts, fill_price, "tp"))
            else:
                break
        return fills

    def on_tick(self, trade: Trade, ts: int, price: float) -> list[Fill]:
        """Procesa un tick de precio (paper trading). Los fills se ejecutan al precio del tick."""
        fills: list[Fill] = []
        if trade.status != OPEN:
            return fills
        side = trade.side

        if side * (price - trade.current_sl) <= 0:
            fills.append(self._close_all(trade, ts, price, self._stop_kind(trade)))
            return fills

        while trade.status == OPEN:
            sp = self.step_price(trade, trade.steps_hit + 1)
            step_hit = side * (price - sp) >= 0
            tp_hit = side * (price - trade.tp) >= 0
            step_before_tp = side * (sp - trade.tp) < 0
            if step_hit and step_before_tp:
                fills.append(self._partial(trade, ts, price, trade.steps_hit + 1))
            elif tp_hit:
                fills.append(self._close_all(trade, ts, price, "tp"))
            else:
                break
        return fills

    def force_close(self, trade: Trade, ts: int, price: float, kind: str = "end") -> list[Fill]:
        """Cierre forzoso (fin de datos en backtest, parada manual en paper)."""
        if trade.status != OPEN:
            return []
        return [self._close_all(trade, ts, price, kind)]
