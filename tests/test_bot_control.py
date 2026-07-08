"""Tests de los endpoints de control del bot y reset de KPIs (modo paper, sin red)."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    # BD aislada y modo paper para no requerir credenciales ni red
    monkeypatch.setenv("BOT_DATA_DIR", str(tmp_path))
    import importlib

    import bot.config as cfg_module

    importlib.reload(cfg_module)
    import bot.persistence.db as db_module

    importlib.reload(db_module)
    from api.main import app

    def fake_config():
        c = cfg_module.load_config()
        c.execution.mode = "paper"
        c.paper.enabled = False
        return c

    with TestClient(app) as tc:
        tc.app.state.config = fake_config()
        tc.app.state.db = db_module.Database(tmp_path / "test.db")
        yield tc
        if tc.app.state.runner:
            tc.app.state.runner.stop()
            tc.app.state.runner = None


def test_account_sin_ejecutar_nada(client):
    r = client.get("/api/account").json()
    assert r["running"] is False
    assert r["execution_mode"] == "paper"
    assert r["bot_pnl_since_reset"] == 0


def test_start_y_stop(client):
    r = client.post("/api/bot/start", json={"capital_fraction_pct": 12.5})
    assert r.status_code == 200
    assert r.json()["running"] is True
    assert r.json()["capital_fraction_pct"] == 12.5

    # doble start -> error
    assert client.post("/api/bot/start", json={}).status_code == 400
    assert client.get("/api/account").json()["running"] is True

    r = client.post("/api/bot/stop", json={"close_positions": False})
    assert r.status_code == 200
    assert r.json()["running"] is False
    assert client.get("/api/account").json()["running"] is False


def test_start_valida_porcentaje(client):
    assert client.post("/api/bot/start", json={"capital_fraction_pct": 0}).status_code == 400
    assert client.post("/api/bot/start", json={"capital_fraction_pct": 150}).status_code == 400


def test_run_now_requiere_bot_en_marcha(client):
    assert client.post("/api/bot/run-now").status_code == 400
    client.post("/api/bot/start", json={"capital_fraction_pct": 5})
    assert client.post("/api/bot/run-now").json()["triggered"] is True
    assert client.post("/api/bot/run-now?entry=market").json()["entry"] == "market"
    assert client.post("/api/bot/run-now?entry=lo-que-sea").status_code == 400
    client.post("/api/bot/stop", json={"close_positions": False})


def test_equity_es_la_banca_no_el_saldo_real(client):
    """El capital de trabajo del bot es referencia + PnL desde reset (no el saldo demo)."""
    from bot.engine.runner import BotRunner

    client.post("/api/account/reset", json={"reference_amount": 1000})
    runner = BotRunner(client.app.state.config, client.app.state.db)
    assert runner.equity() == pytest.approx(1000.0)


def test_reset_fija_referencia_y_baseline(client):
    db = client.app.state.db
    r = client.post("/api/account/reset", json={"reference_amount": 500}).json()
    assert r["reference_capital"] == 500
    assert r["baseline_ts"] > 0
    assert db.baseline_ms() == r["baseline_ts"]

    account = client.get("/api/account").json()
    assert account["reference_capital"] == 500
    assert account["bot_equity"] == 500

    # el summary del dashboard usa la nueva referencia
    summary = client.get("/api/summary?mode=paper").json()
    assert summary["capital_inicial"] == 500
    assert summary["equity"] == 500
    assert summary["closed_trades"] == 0
