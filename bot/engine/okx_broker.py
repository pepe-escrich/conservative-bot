"""Broker OKX vía python-okx (SDK oficial): órdenes reales en la cuenta demo o real.

- Apunta por defecto a OKX Europa (eea.okx.com) con la cabecera de demo trading.
- Convierte tamaños en unidades base a contratos (ctVal/lotSz/minSz del instrumento).
- Devuelve fills reales (precio medio, comisión) para alimentar el estado del bot.

Credenciales: OKX_API_KEY / OKX_API_SECRET / OKX_API_PASSPHRASE (fichero .env).
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

import okx.Account as OkxAccount
import okx.MarketData as OkxMarket
import okx.PublicData as OkxPublic
import okx.Trade as OkxTrade

from bot.config import BotConfig, okx_credentials

log = logging.getLogger("okx")


class BrokerError(Exception):
    pass


@dataclass
class ExecutionResult:
    order_id: str
    price: float       # precio medio ejecutado
    size: float        # unidades base ejecutadas
    fee: float         # comisión pagada (positiva, en la divisa de liquidación)
    time: int          # ms UTC


def to_inst_id(symbol: str) -> str:
    """'BTC/USDT:USDT' (ccxt) -> 'BTC-USDT-SWAP' (OKX)."""
    base, rest = symbol.split("/")
    quote = rest.split(":")[0]
    return f"{base}-{quote}-SWAP"


def _check(resp: dict) -> list[dict]:
    if resp.get("code") != "0":
        detail = resp.get("data") or [{}]
        msg = detail[0].get("sMsg") or resp.get("msg") or str(resp)
        raise BrokerError(f"OKX error {resp.get('code')}: {msg}")
    return resp["data"]


class OKXBroker:
    def __init__(self, config: BotConfig):
        creds = okx_credentials()
        if not creds["api_key"]:
            raise BrokerError(
                "Faltan credenciales OKX: define OKX_API_KEY, OKX_API_SECRET y "
                "OKX_API_PASSPHRASE en el fichero .env de la raíz del proyecto"
            )
        flag = "1" if config.execution.demo else "0"
        domain = config.execution.domain
        kwargs = dict(
            api_key=creds["api_key"],
            api_secret_key=creds["api_secret"],
            passphrase=creds["passphrase"],
            flag=flag,
            domain=domain,
        )
        self.account = OkxAccount.AccountAPI(**kwargs)
        self.trade = OkxTrade.TradeAPI(**kwargs)
        self.public = OkxPublic.PublicAPI(flag=flag, domain=domain)
        self.market = OkxMarket.MarketAPI(flag=flag, domain=domain)
        self.leverage = config.leverage
        self._instruments: dict[str, dict] = {}
        self._leverage_set: set[str] = set()

    # ------------------------------------------------------------------
    # Cuenta
    # ------------------------------------------------------------------

    def balance(self) -> dict:
        """Equity total de la cuenta (USD) y desglose por divisa."""
        data = _check(self.account.get_account_balance())[0]
        details = {
            d["ccy"]: round(float(d.get("eq") or 0), 4)
            for d in data.get("details", [])
            if float(d.get("eq") or 0) != 0
        }
        return {"total_eq_usd": round(float(data.get("totalEq") or 0), 2), "details": details}

    def positions(self) -> list[dict]:
        data = _check(self.account.get_positions(instType="SWAP"))
        out = []
        for p in data:
            if float(p.get("pos") or 0) == 0:
                continue
            spec = self._spec(p["instId"])
            out.append(
                {
                    "inst_id": p["instId"],
                    "contracts": float(p["pos"]),
                    "size": float(p["pos"]) * float(spec["ctVal"]),
                    "avg_price": float(p.get("avgPx") or 0),
                    "upl": float(p.get("upl") or 0),
                }
            )
        return out

    def ensure_net_mode(self) -> None:
        """Modo de posición 'net' (una posición por instrumento). Idempotente."""
        try:
            _check(self.account.set_position_mode(posMode="net_mode"))
        except BrokerError as e:
            log.warning("okx: no se pudo fijar net_mode (%s); se asume ya configurado", e)

    # ------------------------------------------------------------------
    # Instrumentos y precios
    # ------------------------------------------------------------------

    def _spec(self, inst_id: str) -> dict:
        if inst_id not in self._instruments:
            data = _check(self.public.get_instruments(instType="SWAP", instId=inst_id))
            if not data:
                raise BrokerError(f"instrumento {inst_id} no disponible")
            self._instruments[inst_id] = data[0]
        return self._instruments[inst_id]

    def to_contracts(self, symbol: str, size_base: float) -> str:
        """Unidades base -> nº de contratos (string), redondeado al lotSz."""
        spec = self._spec(to_inst_id(symbol))
        ct_val, lot = float(spec["ctVal"]), float(spec["lotSz"])
        contracts = math.floor(size_base / ct_val / lot) * lot
        if contracts < float(spec["minSz"]):
            raise BrokerError(
                f"{symbol}: tamaño {size_base:.8g} = {contracts} contratos < mínimo {spec['minSz']}"
            )
        return f"{contracts:.10f}".rstrip("0").rstrip(".")

    def contracts_to_base(self, inst_id: str, contracts: float) -> float:
        return contracts * float(self._spec(inst_id)["ctVal"])

    def last_prices(self, symbols: list[str]) -> dict[str, float]:
        data = _check(self.market.get_tickers(instType="SWAP"))
        by_inst = {t["instId"]: float(t["last"]) for t in data if t.get("last")}
        return {s: by_inst[to_inst_id(s)] for s in symbols if to_inst_id(s) in by_inst}

    def _ensure_leverage(self, inst_id: str) -> None:
        if inst_id in self._leverage_set:
            return
        try:
            _check(self.account.set_leverage(instId=inst_id, lever=str(int(self.leverage)), mgnMode="cross"))
        except BrokerError as e:
            log.warning("okx: set_leverage %s: %s", inst_id, e)
        self._leverage_set.add(inst_id)

    # ------------------------------------------------------------------
    # Órdenes
    # ------------------------------------------------------------------

    def _order_result(self, inst_id: str, order_id: str) -> ExecutionResult:
        detail = _check(self.trade.get_order(instId=inst_id, ordId=order_id))[0]
        filled_contracts = float(detail.get("accFillSz") or 0)
        return ExecutionResult(
            order_id=order_id,
            price=float(detail.get("avgPx") or 0),
            size=self.contracts_to_base(inst_id, filled_contracts),
            fee=abs(float(detail.get("fee") or 0)),
            time=int(detail.get("fillTime") or detail.get("uTime") or time.time() * 1000),
        )

    def market_order(self, symbol: str, side: str, size_base: float, reduce_only: bool = False) -> ExecutionResult:
        """Orden a mercado. side: 'buy' | 'sell'. Devuelve el fill real."""
        inst_id = to_inst_id(symbol)
        self._ensure_leverage(inst_id)
        sz = self.to_contracts(symbol, size_base)
        data = _check(
            self.trade.place_order(
                instId=inst_id, tdMode="cross", side=side, ordType="market", sz=sz,
                reduceOnly="true" if reduce_only else "false",
            )
        )
        order_id = data[0]["ordId"]
        # las market en OKX llenan de inmediato; pequeño reintento por consistencia eventual
        for _ in range(5):
            result = self._order_result(inst_id, order_id)
            if result.size > 0:
                return result
            time.sleep(0.3)
        raise BrokerError(f"orden market {order_id} en {inst_id} sin fill")

    def limit_order(self, symbol: str, side: str, size_base: float, price: float) -> str:
        """Orden limitada (entrada por pullback). Devuelve el order_id."""
        inst_id = to_inst_id(symbol)
        self._ensure_leverage(inst_id)
        sz = self.to_contracts(symbol, size_base)
        data = _check(
            self.trade.place_order(
                instId=inst_id, tdMode="cross", side=side, ordType="limit", sz=sz, px=f"{price:.10g}"
            )
        )
        return data[0]["ordId"]

    def order_status(self, symbol: str, order_id: str) -> tuple[str, ExecutionResult | None]:
        """Estado de una orden: ('live'|'filled'|'canceled', fill si lo hay)."""
        inst_id = to_inst_id(symbol)
        detail = _check(self.trade.get_order(instId=inst_id, ordId=order_id))[0]
        state = detail.get("state", "live")
        if state == "filled":
            return "filled", self._order_result(inst_id, order_id)
        return ("canceled" if state in ("canceled", "mmp_canceled") else "live"), None

    def cancel_order(self, symbol: str, order_id: str) -> None:
        try:
            _check(self.trade.cancel_order(instId=to_inst_id(symbol), ordId=order_id))
        except BrokerError as e:
            log.warning("okx: cancelar %s: %s", order_id, e)

    def close_position(self, symbol: str) -> None:
        """Cierra por completo la posición del instrumento (market, reduce)."""
        try:
            _check(self.trade.close_positions(instId=to_inst_id(symbol), mgnMode="cross"))
        except BrokerError as e:
            if "51023" not in str(e):  # 51023 = no hay posición
                raise
