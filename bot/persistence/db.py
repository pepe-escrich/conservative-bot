"""Persistencia en SQLite: trades, fills, equity, scores y runs de backtest.

Una sola BD (data/bot.db) compartida por backtest, paper y la API. El acceso
se serializa con un lock: el volumen de escrituras es bajo.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from bot.config import DATA_DIR
from bot.strategy.models import Fill, Trade

SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT DEFAULT (datetime('now')),
    date_from TEXT NOT NULL,
    date_to TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'running',
    progress REAL NOT NULL DEFAULT 0,
    error TEXT,
    metrics_json TEXT
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    mode TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    entry_time INTEGER NOT NULL,
    size REAL NOT NULL,
    initial_sl REAL NOT NULL,
    tp REAL NOT NULL,
    leverage REAL NOT NULL,
    margin REAL NOT NULL,
    score REAL NOT NULL DEFAULT 0,
    current_sl REAL NOT NULL,
    steps_hit INTEGER NOT NULL DEFAULT 0,
    remaining_size REAL NOT NULL,
    realized_pnl REAL NOT NULL DEFAULT 0,
    fees_paid REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    close_time INTEGER,
    close_reason TEXT
);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL REFERENCES trades(id),
    time INTEGER NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    kind TEXT NOT NULL,
    pnl REAL NOT NULL,
    fee REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS equity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    mode TEXT NOT NULL,
    time INTEGER NOT NULL,
    equity REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    mode TEXT NOT NULL,
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    score REAL NOT NULL,
    side TEXT NOT NULL,
    breakdown_json TEXT NOT NULL DEFAULT '{}',
    selected INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS last_prices (
    symbol TEXT PRIMARY KEY,
    price REAL NOT NULL,
    time INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_run ON trades(run_id, status);
CREATE INDEX IF NOT EXISTS idx_fills_trade ON fills(trade_id);
CREATE INDEX IF NOT EXISTS idx_equity_run ON equity_snapshots(run_id, time);
"""


class Database:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else DATA_DIR / "bot.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # ------------------------------------------------------------------
    # Runs de backtest
    # ------------------------------------------------------------------

    def create_run(self, date_from: str, date_to: str, params: dict) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO backtest_runs (date_from, date_to, params_json) VALUES (?, ?, ?)",
                (date_from, date_to, json.dumps(params)),
            )
            self.conn.commit()
            return cur.lastrowid

    def update_run(self, run_id: int, **fields) -> None:
        if "metrics" in fields:
            fields["metrics_json"] = json.dumps(fields.pop("metrics"))
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self._lock:
            self.conn.execute(f"UPDATE backtest_runs SET {cols} WHERE id = ?", (*fields.values(), run_id))
            self.conn.commit()

    def get_runs(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM backtest_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_run(self, run_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM backtest_runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def delete_run(self, run_id: int) -> None:
        with self._lock:
            self.conn.execute(
                "DELETE FROM fills WHERE trade_id IN (SELECT id FROM trades WHERE run_id = ?)", (run_id,)
            )
            self.conn.execute("DELETE FROM trades WHERE run_id = ?", (run_id,))
            self.conn.execute("DELETE FROM equity_snapshots WHERE run_id = ?", (run_id,))
            self.conn.execute("DELETE FROM daily_scores WHERE run_id = ?", (run_id,))
            self.conn.execute("DELETE FROM backtest_runs WHERE id = ?", (run_id,))
            self.conn.commit()

    # ------------------------------------------------------------------
    # Trades y fills
    # ------------------------------------------------------------------

    def save_trade(self, trade: Trade, run_id: int | None = None) -> int:
        """Inserta o actualiza el trade y sincroniza sus fills."""
        values = {
            "run_id": run_id,
            "mode": trade.mode,
            "symbol": trade.symbol,
            "side": trade.side_name,
            "entry_price": trade.entry_price,
            "entry_time": trade.entry_time,
            "size": trade.size,
            "initial_sl": trade.initial_sl,
            "tp": trade.tp,
            "leverage": trade.leverage,
            "margin": trade.margin,
            "score": trade.score,
            "current_sl": trade.current_sl,
            "steps_hit": trade.steps_hit,
            "remaining_size": trade.remaining_size,
            "realized_pnl": trade.realized_pnl,
            "fees_paid": trade.fees_paid,
            "status": trade.status,
            "close_time": trade.close_time,
            "close_reason": trade.close_reason,
        }
        with self._lock:
            if trade.id is None:
                cols = ", ".join(values)
                marks = ", ".join("?" for _ in values)
                cur = self.conn.execute(
                    f"INSERT INTO trades ({cols}) VALUES ({marks})", tuple(values.values())
                )
                trade.id = cur.lastrowid
            else:
                sets = ", ".join(f"{k} = ?" for k in values)
                self.conn.execute(
                    f"UPDATE trades SET {sets} WHERE id = ?", (*values.values(), trade.id)
                )
            self.conn.execute("DELETE FROM fills WHERE trade_id = ?", (trade.id,))
            self.conn.executemany(
                "INSERT INTO fills (trade_id, time, price, size, kind, pnl, fee) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(trade.id, f.time, f.price, f.size, f.kind, f.pnl, f.fee) for f in trade.fills],
            )
            self.conn.commit()
        return trade.id

    def get_trades(
        self,
        mode: str | None = None,
        run_id: int | None = None,
        status: str | None = None,
        symbol: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        query = "SELECT * FROM trades WHERE 1=1"
        params: list = []
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        if run_id is not None:
            query += " AND run_id = ?"
            params.append(run_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        query += " ORDER BY entry_time DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.conn.execute(query, params).fetchall()]

    def get_fills(self, trade_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM fills WHERE trade_id = ? ORDER BY time", (trade_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Equity y scores
    # ------------------------------------------------------------------

    def add_equity_snapshot(self, mode: str, time_ms: int, equity: float, run_id: int | None = None):
        with self._lock:
            self.conn.execute(
                "INSERT INTO equity_snapshots (run_id, mode, time, equity) VALUES (?, ?, ?, ?)",
                (run_id, mode, time_ms, equity),
            )
            self.conn.commit()

    def get_equity_curve(self, mode: str, run_id: int | None = None) -> list[dict]:
        if run_id is not None:
            rows = self.conn.execute(
                "SELECT time, equity FROM equity_snapshots WHERE run_id = ? ORDER BY time", (run_id,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT time, equity FROM equity_snapshots WHERE mode = ? AND run_id IS NULL ORDER BY time",
                (mode,),
            ).fetchall()
        return [dict(r) for r in rows]

    def save_scores(
        self, mode: str, date: str, scores: list, selected: set[str], run_id: int | None = None
    ):
        with self._lock:
            self.conn.executemany(
                "INSERT INTO daily_scores (run_id, mode, date, symbol, score, side, breakdown_json, selected)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (run_id, mode, date, s.symbol, s.score, s.side, json.dumps(s.breakdown), int(s.symbol in selected))
                    for s in scores
                ],
            )
            self.conn.commit()

    def upsert_prices(self, prices: dict[str, float], time_ms: int) -> None:
        with self._lock:
            self.conn.executemany(
                "INSERT INTO last_prices (symbol, price, time) VALUES (?, ?, ?)"
                " ON CONFLICT(symbol) DO UPDATE SET price = excluded.price, time = excluded.time",
                [(s, p, time_ms) for s, p in prices.items()],
            )
            self.conn.commit()

    def get_prices(self) -> dict[str, float]:
        rows = self.conn.execute("SELECT symbol, price FROM last_prices").fetchall()
        return {r["symbol"]: r["price"] for r in rows}

    def load_open_trades(self, mode: str = "paper") -> list[Trade]:
        """Reconstruye los Trade abiertos (con sus fills) para reanudar la gestión."""
        rows = self.get_trades(mode=mode, status="open")
        trades = []
        for r in rows:
            trade = Trade(
                symbol=r["symbol"],
                side=1 if r["side"] == "long" else -1,
                entry_price=r["entry_price"],
                entry_time=r["entry_time"],
                size=r["size"],
                initial_sl=r["initial_sl"],
                tp=r["tp"],
                leverage=r["leverage"],
                margin=r["margin"],
                score=r["score"],
                mode=r["mode"],
                current_sl=r["current_sl"],
                steps_hit=r["steps_hit"],
                remaining_size=r["remaining_size"],
                realized_pnl=r["realized_pnl"],
                fees_paid=r["fees_paid"],
                status=r["status"],
                close_time=r["close_time"],
                close_reason=r["close_reason"],
                id=r["id"],
            )
            trade.fills = [
                Fill(time=f["time"], price=f["price"], size=f["size"], kind=f["kind"], pnl=f["pnl"], fee=f["fee"])
                for f in self.get_fills(trade.id)
            ]
            trades.append(trade)
        return trades

    def total_realized_pnl(self, mode: str = "paper") -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) AS s FROM trades WHERE mode = ? AND run_id IS NULL",
            (mode,),
        ).fetchone()
        return row["s"]

    def get_recent_fills(self, mode: str, since_ms: int) -> list[dict]:
        """Fills (con símbolo) desde un instante, para PnL del día. Solo paper/live (run_id NULL)."""
        rows = self.conn.execute(
            "SELECT f.*, t.symbol, t.side FROM fills f JOIN trades t ON t.id = f.trade_id"
            " WHERE t.mode = ? AND t.run_id IS NULL AND f.time >= ? ORDER BY f.time",
            (mode, since_ms),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_scores(self, date: str | None = None, mode: str = "paper", run_id: int | None = None) -> list[dict]:
        query = "SELECT * FROM daily_scores WHERE mode = ?"
        params: list = [mode]
        if run_id is not None:
            query = "SELECT * FROM daily_scores WHERE run_id = ?"
            params = [run_id]
        if date:
            query += " AND date = ?"
            params.append(date)
        query += " ORDER BY date DESC, ABS(score) DESC LIMIT 500"
        return [dict(r) for r in self.conn.execute(query, params).fetchall()]
