"""Construcción del trade: entrada, SL por ATR, TP a RR:1 y tamaño por riesgo fijo."""

from __future__ import annotations

import pandas as pd

from bot.config import BotConfig
from bot.indicators.classic import atr
from bot.strategy.models import LONG, Fill, Trade


def build_trade(
    symbol: str,
    side: int,
    entry_time: int,
    market_price: float,
    signal_df: pd.DataFrame,
    equity: float,
    available_margin: float,
    config: BotConfig,
    score: float = 0.0,
    mode: str = "backtest",
    atr_value: float | None = None,
    entry_type: str = "market",
) -> Trade | None:
    """Crea un Trade listo para gestionar, o None si no hay margen/datos suficientes.

    - SL a `stop.atr_mult` ATRs de la entrada; TP a `risk_reward` veces esa distancia.
    - Tamaño tal que si salta el SL inicial se pierde `risk_per_trade_pct`% del equity.
    - entry_type 'market': paga slippage y comisión taker; 'limit' (pullback):
      sin slippage y comisión maker.
    - `atr_value` permite inyectar un ATR precalculado (optimizador/pendientes);
      si no, se calcula sobre `signal_df`.
    """
    if atr_value is None:
        if len(signal_df) < config.stop.atr_period + 5:
            return None
        atr_value = float(atr(signal_df, config.stop.atr_period).iloc[-1])

    if entry_type == "limit":
        entry = market_price
        fee_pct = config.fees.maker_pct
    else:
        entry = market_price * (1 + side * config.fees.slippage_pct / 100)
        fee_pct = config.fees.taker_pct
    sl_distance = config.stop.atr_mult * atr_value
    if sl_distance <= 0:
        return None

    initial_sl = entry - side * sl_distance
    tp = entry + side * config.risk_reward * sl_distance
    if initial_sl <= 0:
        return None

    if config.sizing.mode == "capital_fraction":
        # margen = % fijo del capital al inicio del día
        margin = min(equity * config.sizing.capital_fraction_pct / 100, available_margin)
        size = margin * config.leverage / entry
    else:
        # tamaño por riesgo: perder risk_per_trade_pct% del equity si salta el SL
        risk_amount = equity * config.risk_per_trade_pct / 100
        size = risk_amount / sl_distance
        margin = size * entry / config.leverage
        if margin > available_margin:
            # no hay margen libre suficiente: reducir la posición
            margin = available_margin
            size = margin * config.leverage / entry
    if margin <= 0 or size * entry < 1:  # notional mínimo de 1 USDT
        return None

    open_fee = size * entry * fee_pct / 100
    trade = Trade(
        symbol=symbol,
        side=side,
        entry_price=entry,
        entry_time=entry_time,
        size=size,
        initial_sl=initial_sl,
        tp=tp,
        leverage=config.leverage,
        margin=margin,
        score=score,
        mode=mode,
    )
    trade.fills.append(Fill(time=entry_time, price=entry, size=size, kind="open", pnl=0.0, fee=open_fee))
    trade.fees_paid = open_fee
    trade.realized_pnl = -open_fee
    return trade


def side_from_score(score: float) -> int:
    return LONG if score >= 0 else -1
