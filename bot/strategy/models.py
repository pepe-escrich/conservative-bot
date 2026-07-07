"""Modelos de dominio: Trade y Fill. Compartidos por backtest, paper y API."""

from __future__ import annotations

from dataclasses import dataclass, field


LONG = 1
SHORT = -1

OPEN = "open"
CLOSED = "closed"


@dataclass
class Fill:
    time: int              # ms UTC
    price: float           # precio ejecutado (slippage incluido)
    size: float            # unidades de base cerradas/abiertas
    kind: str              # 'open' | 'step' | 'sl' | 'be' | 'trail' | 'tp' | 'ladder' | 'end'
    pnl: float             # PnL bruto del fill (0 en apertura)
    fee: float             # comisión pagada


@dataclass
class PendingEntry:
    """Orden limitada de entrada (modo pullback) a la espera de fill o expiración."""

    symbol: str
    side: int
    limit_price: float
    created: int           # ms UTC
    expires: int           # ms UTC
    score: float
    atr_value: float       # ATR capturado en el momento de la señal
    signal_price: float    # precio cuando se eligió el token


@dataclass
class Trade:
    symbol: str
    side: int              # LONG (+1) o SHORT (-1)
    entry_price: float     # precio de entrada ejecutado
    entry_time: int        # ms UTC
    size: float            # tamaño inicial en unidades de base
    initial_sl: float
    tp: float
    leverage: float
    margin: float          # margen usado (notional / leverage)
    score: float = 0.0     # puntuación con la que se abrió
    mode: str = "backtest"  # 'backtest' | 'paper'

    current_sl: float = 0.0
    steps_hit: int = 0
    remaining_size: float = 0.0
    realized_pnl: float = 0.0   # neto de comisiones (incluida la de apertura)
    fees_paid: float = 0.0
    status: str = OPEN
    close_time: int | None = None
    close_reason: str | None = None
    fills: list[Fill] = field(default_factory=list)
    id: int | None = None       # asignado por la BD

    def __post_init__(self):
        if self.current_sl == 0.0:
            self.current_sl = self.initial_sl
        if self.remaining_size == 0.0:
            self.remaining_size = self.size

    @property
    def notional(self) -> float:
        return self.size * self.entry_price

    @property
    def side_name(self) -> str:
        return "long" if self.side == LONG else "short"

    def unrealized_pnl(self, price: float) -> float:
        return self.side * (price - self.entry_price) * self.remaining_size
