# conservative-bot

Bot de trading de perpetuos cripto con operativa diaria sencilla:

- **N trades al día** (configurable, hoy 3) a las **07:00** (Europe/Madrid), LONG o SHORT, leverage configurable (hoy 3x).
- Puntúa el catálogo de tokens con indicadores (EMA, RSI, MACD, ADX, Bollinger) + **FRVP** y abre los de mayor puntuación (umbral `min_score`).
- SL por ATR, TP a `risk_reward`·R (hoy 4,23R).
- **Gestión por escalones** de precio: cada +`step_pct`% cierra `partial_close_pct`% y arrastra el SL (breakeven o escalón anterior) hasta que salte el SL o llegue al TP.
- **Backtest** con comisiones y slippage, **paper trading** en tiempo real (datos públicos de ccxt, sin API keys) y **dashboard web** (React). Parámetros afinados por Optuna (validación IS/OOS).

> ⚠️ Los valores por defecto vienen de un estudio Optuna sobre 2 años (ver `config.yaml` y `data/studies/`). Valida siempre con backtest antes de creerte nada; un escalón demasiado fino se lo comen las comisiones.

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

## Modos de ejecución

El bot tiene dos modos (`execution.mode` en `config.yaml`):

- **`paper`** (default, recomendado para validar): trading simulado contra datos
  públicos de ccxt (sin API keys, sin cuenta). Misma estrategia y universo que en
  producción. Así está configurado ahora.
- **`okx`**: órdenes reales vía el SDK oficial `python-okx` contra OKX Europa
  (`eea.okx.com`), cuenta demo o real según `execution.demo`.

> ⚠️ **OKX EU bloquea los perps estándar (error 51155, MiCA/MiFID)**: la cuenta de OKX
> Europa **no puede operar perpetuals SWAP** (USDT/USD/USDC). Solo son operables los
> **X-Perps** regulados (`instType=FUTURES`, instId `BASE-USD_UM_XPERP`, USD-margined).
> El broker (`bot/engine/okx_broker.py`) aún mapea a SWAP; para ejecución real hay que
> adaptarlo a X-Perps (fase 2) y pasar el test de idoneidad MiFID en la cuenta real.
> Mientras tanto el bot corre en `paper` (fiel: universo de 30 X-Perps + datos USDT-perp
> como proxy del mismo subyacente).

Para `paper`: arranca la web y usa el panel — **Iniciar bot** (% de capital por trade),
**Parar** (pregunta si cerrar posiciones), **Reset** (nuevo capital de referencia +
KPIs). No requiere claves OKX (`.env` puede llevar las variables vacías).

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
