"""Manager de escalones con ejecución real: los cierres se envían a OKX.

Hereda toda la lógica de disparo (escalones, trailing, SL, TP) de
StepLadderManager y solo sustituye la ejecución simulada por órdenes reales,
registrando el fill con el precio medio y la comisión que devuelve OKX.
"""

from __future__ import annotations

import logging

from bot.config import BotConfig
from bot.engine.okx_broker import BrokerError, OKXBroker
from bot.strategy.manager import StepLadderManager
from bot.strategy.models import CLOSED, Fill, Trade

log = logging.getLogger("okx")


class LiveLadderManager(StepLadderManager):
    def __init__(self, config: BotConfig, broker: OKXBroker):
        super().__init__(config)
        self.broker = broker

    def _fill_close(self, trade: Trade, ts: int, price: float, qty: float, kind: str) -> Fill:
        """Cierre (parcial o total) vía orden market reduce-only; fill con datos reales."""
        side = "sell" if trade.side > 0 else "buy"
        result = self.broker.market_order(trade.symbol, side, qty, reduce_only=True)
        gross = trade.side * (result.price - trade.entry_price) * result.size
        fill = Fill(time=result.time, price=result.price, size=result.size, kind=kind, pnl=gross, fee=result.fee)
        trade.fills.append(fill)
        trade.remaining_size -= result.size
        trade.realized_pnl += gross - result.fee
        trade.fees_paid += result.fee
        return fill

    def _partial(self, trade: Trade, ts: int, price: float, k: int) -> Fill:
        # si el parcial queda por debajo del tamaño mínimo de contrato, cerrar todo
        qty = trade.remaining_size * self.steps.partial_close_pct / 100
        try:
            self.broker.to_contracts(trade.symbol, qty)
        except BrokerError:
            return self._close_all(trade, ts, price, "ladder")
        return super()._partial(trade, ts, price, k)

    def _close_all(self, trade: Trade, ts: int, price: float, kind: str) -> Fill:
        fill = self._fill_close(trade, ts, price, trade.remaining_size, kind)
        trade.status = CLOSED
        trade.close_time = fill.time
        trade.close_reason = kind
        trade.remaining_size = 0.0
        # barrer el resto por redondeo de contratos, si lo hubiera
        try:
            self.broker.close_position(trade.symbol)
        except BrokerError as e:
            log.warning("okx: barrido de resto en %s: %s", trade.symbol, e)
        return fill
