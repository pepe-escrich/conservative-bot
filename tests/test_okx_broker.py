"""Tests del broker OKX con el SDK mockeado (sin red ni credenciales)."""

from unittest.mock import MagicMock, patch

import pytest

from bot.config import BotConfig


def make_broker(monkeypatch):
    monkeypatch.setenv("OKX_API_KEY", "k")
    monkeypatch.setenv("OKX_API_SECRET", "s")
    monkeypatch.setenv("OKX_API_PASSPHRASE", "p")
    config = BotConfig(leverage=3, execution={"mode": "okx", "demo": True})
    with patch("bot.engine.okx_broker.OkxAccount"), patch("bot.engine.okx_broker.OkxTrade"), \
         patch("bot.engine.okx_broker.OkxPublic"), patch("bot.engine.okx_broker.OkxMarket"):
        from bot.engine.okx_broker import OKXBroker

        broker = OKXBroker(config)
    broker.account = MagicMock()
    broker.trade = MagicMock()
    broker.public = MagicMock()
    broker.market = MagicMock()
    # instrumento BTC-USDT-SWAP: 1 contrato = 0.01 BTC, lote 0.1, mínimo 0.1
    broker.public.get_instruments.return_value = {
        "code": "0",
        "data": [{"instId": "BTC-USDT-SWAP", "ctVal": "0.01", "lotSz": "0.1", "minSz": "0.1"}],
    }
    return broker


def test_to_inst_id():
    from bot.engine.okx_broker import to_inst_id

    assert to_inst_id("BTC/USDT:USDT") == "BTC-USDT-SWAP"
    assert to_inst_id("PEPE/USDT:USDT") == "PEPE-USDT-SWAP"


def test_to_contracts_redondea_al_lote(monkeypatch):
    broker = make_broker(monkeypatch)
    # 0.0567 BTC / 0.01 = 5.67 contratos -> floor a 5.6
    assert broker.to_contracts("BTC/USDT:USDT", 0.0567) == "5.6"


def test_to_contracts_por_debajo_del_minimo(monkeypatch):
    from bot.engine.okx_broker import BrokerError

    broker = make_broker(monkeypatch)
    with pytest.raises(BrokerError, match="mínimo"):
        broker.to_contracts("BTC/USDT:USDT", 0.0005)  # 0.05 contratos < minSz 0.1


def test_market_order_devuelve_fill_real(monkeypatch):
    broker = make_broker(monkeypatch)
    broker.trade.place_order.return_value = {"code": "0", "data": [{"ordId": "123"}]}
    broker.trade.get_order.return_value = {
        "code": "0",
        "data": [{"state": "filled", "avgPx": "50000", "accFillSz": "5.6", "fee": "-1.4", "fillTime": "1700000000000"}],
    }
    broker.account.set_leverage.return_value = {"code": "0", "data": []}

    result = broker.market_order("BTC/USDT:USDT", "buy", 0.0567)

    assert result.price == 50000.0
    assert result.size == pytest.approx(0.056)  # 5.6 contratos * 0.01
    assert result.fee == pytest.approx(1.4)     # valor absoluto
    call = broker.trade.place_order.call_args.kwargs
    assert call["instId"] == "BTC-USDT-SWAP"
    assert call["ordType"] == "market"
    assert call["sz"] == "5.6"


def test_error_de_okx_lanza_broker_error(monkeypatch):
    from bot.engine.okx_broker import BrokerError

    broker = make_broker(monkeypatch)
    broker.trade.place_order.return_value = {
        "code": "1", "msg": "", "data": [{"sMsg": "Insufficient balance"}],
    }
    broker.account.set_leverage.return_value = {"code": "0", "data": []}
    with pytest.raises(BrokerError, match="Insufficient balance"):
        broker.market_order("BTC/USDT:USDT", "buy", 0.0567)


def test_balance(monkeypatch):
    broker = make_broker(monkeypatch)
    broker.account.get_account_balance.return_value = {
        "code": "0",
        "data": [{"totalEq": "1234.56", "details": [
            {"ccy": "USDC", "eq": "1000"}, {"ccy": "USDT", "eq": "234.5"}, {"ccy": "BTC", "eq": "0"},
        ]}],
    }
    bal = broker.balance()
    assert bal["total_eq_usd"] == 1234.56
    assert bal["details"] == {"USDC": 1000.0, "USDT": 234.5}
