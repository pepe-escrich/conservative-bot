"""Aplicación FastAPI: API REST + estáticos del frontend + paper runner opcional."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import backtests, bot, data
from bot.config import PROJECT_ROOT, load_config
from bot.persistence.db import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("api")

WEB_DIST = PROJECT_ROOT / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    app.state.config = config
    app.state.db = Database()
    app.state.runner = None
    # autoarranque: si estaba en marcha (bot_state) o el modo paper clásico está activado
    should_run = config.paper.enabled or app.state.db.get_state("running") == "1"
    if should_run:
        from bot.engine.runner import BotRunner

        try:
            runner = BotRunner(config, app.state.db)
            runner.start()
            app.state.runner = runner
        except Exception as e:
            log.error("no se pudo autoarrancar el bot: %s", e)
    yield
    if app.state.runner:
        app.state.runner.stop()


app = FastAPI(title="conservative-bot", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

app.include_router(data.router, prefix="/api")
app.include_router(backtests.router, prefix="/api")
app.include_router(bot.router, prefix="/api")

if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
