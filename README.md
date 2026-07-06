# conservative-bot

Bot de trading de perpetuos cripto con operativa diaria sencilla:

- **3 trades al día** (configurable) a las **07:00** (configurable, Europe/Madrid), LONG o SHORT, **10x**.
- Puntúa el catálogo de tokens con indicadores (EMA, RSI, MACD, ADX, Bollinger) + **FRVP** y abre los N con mayor puntuación.
- Setup **1:3** (configurable): SL por ATR, TP a 3R.
- **Gestión por escalones**: cada +1% de PnL sobre el margen → SL a breakeven (luego trailing) y cierre del 50% restante, hasta que salte el SL o llegue al TP.
- **Backtest** con comisiones y slippage, **paper trading** en tiempo real (OKX, datos públicos, sin API keys) y **dashboard web** (React).

> ⚠️ A 10x, un escalón del 1% de PnL equivale a 0,1% de precio; las comisiones taker de ida y vuelta (~0,1% del notional) consumen ~1% del margen. Usa el backtest para validar los parámetros antes de creerte nada.

## Estructura

- `bot/` — núcleo: datos (ccxt/OKX), indicadores, scoring, estrategia, backtest, paper, SQLite
- `api/` — FastAPI (REST + estáticos del frontend + runner de paper)
- `web/` — dashboard React (Vite + TS + Tailwind)
- `config/config.yaml` — **todos** los parámetros operativos
- `data/` — velas (parquet) y base de datos (gitignored)

## Uso en local

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# 1. Descargar velas de OKX (una vez; luego actualiza incremental)
.venv/bin/python -m bot fetch --days 120

# 2. Backtest por CLI (también desde la web)
.venv/bin/python -m bot backtest --from 2026-04-01 --to 2026-06-30

# 3. Web: API + frontend
.venv/bin/uvicorn api.main:app --port 8000        # backend
cd web && npm install && npm run dev              # frontend en http://localhost:5173

# Tests
.venv/bin/python -m pytest
```

Para el **paper trading**, pon `paper.enabled: true` en `config/config.yaml` y arranca la API: el bot puntuará y abrirá trades cada día a la hora configurada, gestionándolos con precios reales.

## Despliegue en Hetzner Cloud

Cualquier VPS pequeño sirve (CX22, 2 vCPU / 4 GB). Con Docker instalado:

```bash
# en el servidor
git clone <tu-repo> && cd conservative-bot
docker compose up -d --build

# descargar velas dentro del contenedor (primera vez)
docker compose exec bot python -m bot fetch --days 120
```

La web queda en `http://IP-del-servidor:8000`. El estado (velas + BD) persiste en `./data`; la config se puede editar en `./config/config.yaml` y reiniciar con `docker compose restart`.

Recomendado: poner delante un Caddy/Traefik con TLS y restringir el puerto con el firewall de Hetzner si no quieres exponer el dashboard.

## Configuración (config/config.yaml)

| Clave | Descripción |
|---|---|
| `universe` | catálogo de tokens (formato ccxt `BTC/USDT:USDT`) |
| `schedule.time` / `timezone` | hora de apertura diaria |
| `trades_per_day` / `min_score` | nº de trades y umbral de puntuación |
| `leverage` / `risk_per_trade_pct` | apalancamiento y % de equity arriesgado por trade |
| `risk_reward` / `stop.atr_mult` | setup 1:3 y distancia del SL en ATRs |
| `steps.*` | escalones: base (PnL margen o precio), tamaño, % de cierre, trailing |
| `fees.*` | comisión taker y slippage simulados |
| `indicators.*` | pesos del scoring (añadir indicadores en `bot/scoring/scorer.py`) |

## Añadir un indicador nuevo

1. Implementa una función `(ctx: SignalContext) -> float` en `bot/indicators/` que devuelva una señal en [-1, +1].
2. Regístrala en `SIGNALS` (`bot/scoring/scorer.py`).
3. Dale peso en `config.yaml` → `indicators:`. Listo: entra en el scoring, el backtest y el paper.
