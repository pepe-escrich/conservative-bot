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

# 0. (opcional) Regenerar el catálogo: top-50 por capitalización con perpetuo en OKX
.venv/bin/python -m bot universe --top 50   # imprime el bloque para config.yaml

# 1. Descargar velas de OKX (una vez; luego actualiza incremental)
.venv/bin/python -m bot fetch --days 120

# 2. Backtest por CLI (también desde la web)
.venv/bin/python -m bot backtest --from 2026-04-01 --to 2026-06-30

# 2b. Estudio de optimización (Optuna): busca los parámetros más idóneos
#     con validación in-sample/out-of-sample para evitar sobreajuste.
#     Genera un informe en data/studies/ y guarda el mejor run en la web.
.venv/bin/python -m bot optimize --from 2026-04-15 --to 2026-07-05 --trials 200

# 3. Web: API + frontend
.venv/bin/uvicorn api.main:app --port 8000        # backend
cd web && npm install && npm run dev              # frontend en http://localhost:5173

# Tests
.venv/bin/python -m pytest
```

Para el **paper trading**, pon `paper.enabled: true` en `config/config.yaml` y arranca la API: el bot puntuará y abrirá trades cada día a la hora configurada, gestionándolos con precios reales.

## Conexión con la cuenta demo de OKX

La ejecución real (demo o live) usa el SDK oficial `python-okx` contra **OKX Europa**
(`eea.okx.com`); se controla en `config.yaml`:

```yaml
execution:
  mode: okx     # 'paper' = simulado interno; 'okx' = órdenes reales
  domain: https://eea.okx.com
  demo: true    # demo trading (flag 1)
```

1. Crea una API key de **demo trading** en OKX (permiso *Trade*).
2. `cp .env.example .env` y rellena `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_API_PASSPHRASE`.
3. Arranca la web y usa el panel del dashboard: **Iniciar bot** (con el % de capital
   por trade), **Parar** (pregunta si cerrar posiciones) y **Reset** (nuevo capital de
   referencia + limpieza de KPIs; el saldo demo real se recarga desde la web de OKX).

Nota: los perps lineales de OKX (también en la entidad europea) liquidan en USDT;
el "USD-M" de OKX EU significa que puedes usar USDC/USD como colateral de margen.

## Despliegue en Hetzner Cloud

Cualquier VPS pequeño sirve (CX22, 2 vCPU / 4 GB, ~4 €/mes) con Ubuntu 24.04 + Docker.

```bash
# en el servidor (una vez): instalar docker si no lo tiene
curl -fsSL https://get.docker.com | sh

# desplegar
git clone https://github.com/pepe-escrich/conservative-bot.git && cd conservative-bot
cp .env.example .env && nano .env          # pegar las API keys de OKX demo
docker compose up -d --build

# primera vez: descargar histórico de velas dentro del contenedor
docker compose exec bot python -m bot fetch --days 120
```

La web queda en `http://IP-del-servidor:8000`. El estado (velas + BD + estado del bot)
persiste en `./data`; la config se edita en `./config/config.yaml` y se aplica con
`docker compose restart`. Actualizar versión: `git pull && docker compose up -d --build`.

Seguridad: el dashboard no tiene login — restringe el puerto 8000 en el firewall de
Hetzner a tu IP, o pon delante Caddy/Traefik con TLS y basic auth.

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
