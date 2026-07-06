"""Tests del manager de escalones: BE, trailing, parciales, TP, SL intra-vela, dust."""

import pytest

from bot.strategy.manager import StepLadderManager
from bot.strategy.models import CLOSED, LONG, OPEN, SHORT, Trade


def make_trade(side=LONG, entry=100.0, size=1.0, sl=95.0, tp=115.0, leverage=10.0):
    return Trade(
        symbol="BTC/USDT:USDT",
        side=side,
        entry_price=entry,
        entry_time=0,
        size=size,
        initial_sl=sl,
        tp=tp,
        leverage=leverage,
        margin=entry * size / leverage,
    )


def test_primer_escalon_cierra_50_y_mueve_sl_a_breakeven(config):
    mgr = StepLadderManager(config)
    trade = make_trade()
    fills = mgr.on_candle(trade, ts=1, o=100.0, h=101.5, l=99.5, c=101.0)

    assert len(fills) == 1
    assert fills[0].kind == "step"
    assert fills[0].price == pytest.approx(101.0)   # precio del escalón 1 (base 'price', 1%)
    assert fills[0].size == pytest.approx(0.5)
    assert trade.steps_hit == 1
    assert trade.current_sl == pytest.approx(100.0)  # breakeven
    assert trade.remaining_size == pytest.approx(0.5)
    assert trade.realized_pnl == pytest.approx(0.5)  # (101-100)*0.5, sin fees
    assert trade.status == OPEN


def test_segundo_escalon_trailing_al_escalon_anterior(config):
    mgr = StepLadderManager(config)
    trade = make_trade()
    mgr.on_candle(trade, ts=1, o=100.0, h=101.2, l=99.9, c=101.0)
    fills = mgr.on_candle(trade, ts=2, o=101.0, h=102.3, l=100.8, c=102.0)

    assert len(fills) == 1
    assert fills[0].price == pytest.approx(102.0)
    assert fills[0].size == pytest.approx(0.25)
    assert trade.steps_hit == 2
    assert trade.current_sl == pytest.approx(101.0)  # precio del escalón 1
    assert trade.remaining_size == pytest.approx(0.25)


def test_breakeven_only_no_trailing(config):
    config.steps.trail_mode = "breakeven_only"
    mgr = StepLadderManager(config)
    trade = make_trade()
    mgr.on_candle(trade, ts=1, o=100.0, h=102.5, l=99.9, c=102.0)  # escalones 1 y 2

    assert trade.steps_hit == 2
    assert trade.current_sl == pytest.approx(100.0)  # sigue en breakeven


def test_sl_trailing_salta_y_cierra_con_beneficio(config):
    mgr = StepLadderManager(config)
    trade = make_trade()
    mgr.on_candle(trade, ts=1, o=100.0, h=101.2, l=99.9, c=101.0)
    mgr.on_candle(trade, ts=2, o=101.0, h=102.3, l=100.8, c=102.0)
    fills = mgr.on_candle(trade, ts=3, o=102.0, h=102.2, l=100.5, c=100.6)  # cae hasta el SL (101)

    assert trade.status == CLOSED
    assert trade.close_reason == "trail"
    assert fills[-1].price == pytest.approx(101.0)
    # PnL total: 0.5@+1 + 0.25@+2 + 0.25@+1 = 1.25
    assert trade.realized_pnl == pytest.approx(0.5 * 1 + 0.25 * 2 + 0.25 * 1)


def test_sl_inicial_pierde_lo_esperado(config):
    mgr = StepLadderManager(config)
    trade = make_trade()  # sl=95, size=1
    fills = mgr.on_candle(trade, ts=1, o=100.0, h=100.5, l=94.0, c=94.5)

    assert trade.status == CLOSED
    assert trade.close_reason == "sl"
    assert fills[0].price == pytest.approx(95.0)
    assert trade.realized_pnl == pytest.approx(-5.0)


def test_conservador_sl_antes_que_escalon_en_la_misma_vela(config):
    """Si la vela toca SL y escalón, se asume SL primero: sin parciales."""
    mgr = StepLadderManager(config)
    trade = make_trade()
    fills = mgr.on_candle(trade, ts=1, o=100.0, h=101.5, l=94.0, c=95.0)

    assert trade.status == CLOSED
    assert trade.close_reason == "sl"
    assert len(fills) == 1
    assert trade.steps_hit == 0


def test_tp_cierra_el_resto_tras_los_escalones(config):
    mgr = StepLadderManager(config)
    trade = make_trade(tp=103.0)  # escalones a 101, 102; el 3 (103) coincide con TP
    fills = mgr.on_candle(trade, ts=1, o=100.0, h=104.0, l=99.9, c=103.5)

    assert [f.kind for f in fills] == ["step", "step", "tp"]
    assert fills[0].price == pytest.approx(101.0)
    assert fills[1].price == pytest.approx(102.0)
    assert fills[2].price == pytest.approx(103.0)
    assert trade.status == CLOSED
    assert trade.close_reason == "tp"
    assert trade.realized_pnl == pytest.approx(0.5 * 1 + 0.25 * 2 + 0.25 * 3)


def test_ladder_dust_cierra_todo(config):
    """Tras varios parciales, el resto es tan pequeño que se cierra entero."""
    mgr = StepLadderManager(config)
    trade = make_trade(tp=200.0)  # TP lejos para que la escalera avance
    mgr.on_candle(trade, ts=1, o=100.0, h=105.0, l=99.9, c=105.0)  # escalones 1..5

    assert trade.status == CLOSED
    assert trade.close_reason == "ladder"
    # remaining tras 4 parciales = 0.0625; el 5º dejaría 0.03125 < 5% de 1.0 -> cierre total
    assert trade.steps_hit == 4
    assert trade.remaining_size == pytest.approx(0.0)


def test_short_simetrico(config):
    mgr = StepLadderManager(config)
    trade = make_trade(side=SHORT, sl=105.0, tp=85.0)
    fills = mgr.on_candle(trade, ts=1, o=100.0, h=100.4, l=98.9, c=99.0)

    assert fills[0].kind == "step"
    assert fills[0].price == pytest.approx(99.0)  # escalón 1 short: -1%
    assert trade.current_sl == pytest.approx(100.0)
    assert trade.realized_pnl == pytest.approx(0.5 * 1)

    mgr.on_candle(trade, ts=2, o=99.0, h=100.5, l=99.0, c=100.4)  # rebote al SL (BE)
    assert trade.status == CLOSED
    assert trade.close_reason == "be"


def test_gap_contra_la_posicion_ejecuta_al_open(config):
    mgr = StepLadderManager(config)
    trade = make_trade()  # sl=95
    fills = mgr.on_candle(trade, ts=1, o=93.0, h=94.0, l=92.0, c=93.5)  # gap por debajo del SL

    assert trade.status == CLOSED
    assert fills[0].price == pytest.approx(93.0)  # peor que el SL teórico
    assert trade.realized_pnl == pytest.approx(-7.0)


def test_step_basis_margin_pnl(config):
    """Con base margin_pnl y 10x, un escalón del 1% de PnL = 0.1% de precio."""
    config.steps.basis = "margin_pnl"
    mgr = StepLadderManager(config)
    trade = make_trade()

    assert mgr.step_price(trade, 1) == pytest.approx(100.1)
    assert mgr.step_price(trade, 3) == pytest.approx(100.3)

    fills = mgr.on_candle(trade, ts=1, o=100.0, h=100.15, l=99.95, c=100.1)
    assert fills[0].price == pytest.approx(100.1)
    assert trade.current_sl == pytest.approx(100.0)


def test_fees_y_slippage_se_descuentan():
    from bot.config import BotConfig

    cfg = BotConfig(
        steps={"basis": "price", "step_pct": 1.0, "partial_close_pct": 50, "trail_mode": "previous_step"},
        fees={"taker_pct": 0.1, "slippage_pct": 0.05},
    )
    mgr = StepLadderManager(cfg)
    trade = make_trade()
    fills = mgr.on_candle(trade, ts=1, o=100.0, h=101.5, l=99.5, c=101.0)

    executed = 101.0 * (1 - 0.05 / 100)  # slippage en contra al cerrar un long
    assert fills[0].price == pytest.approx(executed)
    gross = (executed - 100.0) * 0.5
    fee = executed * 0.5 * 0.1 / 100
    assert trade.realized_pnl == pytest.approx(gross - fee)
    assert trade.fees_paid == pytest.approx(fee)


def test_on_tick_paper(config):
    mgr = StepLadderManager(config)
    trade = make_trade()

    assert mgr.on_tick(trade, 1, 100.5) == []            # nada
    fills = mgr.on_tick(trade, 2, 101.05)                # escalón 1
    assert fills[0].kind == "step"
    assert fills[0].price == pytest.approx(101.05)       # al precio del tick
    assert trade.current_sl == pytest.approx(100.0)

    fills = mgr.on_tick(trade, 3, 99.8)                  # toca BE
    assert trade.status == CLOSED
    assert trade.close_reason == "be"


def test_force_close(config):
    mgr = StepLadderManager(config)
    trade = make_trade()
    fills = mgr.force_close(trade, ts=9, price=100.5)

    assert trade.status == CLOSED
    assert trade.close_reason == "end"
    assert fills[0].pnl == pytest.approx(0.5)
