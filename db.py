import csv
import io
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config import settings


class Database:
    def __init__(self, path: str | None = None):
        self.path = path or settings.database_path
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS vip_subscriptions (
                    user_id INTEGER PRIMARY KEY,
                    start_at TEXT NOT NULL,
                    end_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    notified_expiry INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry REAL NOT NULL,
                    sl REAL NOT NULL,
                    tp1 REAL NOT NULL,
                    tp2 REAL NOT NULL,
                    rr REAL NOT NULL,
                    risk_percent REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    closed_at TEXT,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    tp1_hit INTEGER NOT NULL DEFAULT 0,
                    tp2_hit INTEGER NOT NULL DEFAULT 0,
                    breakeven_alert_sent INTEGER NOT NULL DEFAULT 0,
                    invalidation_alert_sent INTEGER NOT NULL DEFAULT 0,
                    entry_message_id INTEGER,
                    teaser_message_id INTEGER,
                    result_message_id INTEGER,
                    last_price REAL,
                    pnl_pips REAL,
                    notes TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
                CREATE INDEX IF NOT EXISTS idx_trades_symbol_status ON trades(symbol, status);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    trade_id INTEGER,
                    user_id INTEGER,
                    message TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def upsert_user(self, user_id: int, username: str | None, first_name: str | None) -> None:
        now = self.now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO users(user_id, username, first_name, created_at, updated_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,
                   first_name=excluded.first_name, updated_at=excluded.updated_at""",
                (user_id, username, first_name, now, now),
            )

    def grant_vip(self, user_id: int, days: int) -> sqlite3.Row:
        now_dt = datetime.now(timezone.utc)
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM vip_subscriptions WHERE user_id=?", (user_id,)
            ).fetchone()
            if existing and existing["status"] == "active":
                end_dt = datetime.fromisoformat(existing["end_at"])
                start_dt = datetime.fromisoformat(existing["start_at"])
                base = max(end_dt, now_dt)
            else:
                start_dt = now_dt
                base = now_dt
            from datetime import timedelta
            end_dt = base + timedelta(days=days)
            conn.execute(
                """INSERT INTO vip_subscriptions(user_id,start_at,end_at,status,notified_expiry)
                   VALUES(?,?,?,?,0)
                   ON CONFLICT(user_id) DO UPDATE SET start_at=excluded.start_at,
                   end_at=excluded.end_at,status='active',notified_expiry=0""",
                (user_id, start_dt.isoformat(), end_dt.isoformat(), "active"),
            )
            return conn.execute(
                "SELECT * FROM vip_subscriptions WHERE user_id=?", (user_id,)
            ).fetchone()

    def revoke_vip(self, user_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE vip_subscriptions SET status='revoked' WHERE user_id=? AND status='active'",
                (user_id,),
            )
            return cur.rowcount > 0

    def vip_status(self, user_id: int) -> Optional[sqlite3.Row]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM vip_subscriptions WHERE user_id=?", (user_id,)
            ).fetchone()
            if row and row["status"] == "active" and datetime.fromisoformat(row["end_at"]) <= datetime.now(timezone.utc):
                conn.execute(
                    "UPDATE vip_subscriptions SET status='expired' WHERE user_id=?", (user_id,)
                )
                row = conn.execute(
                    "SELECT * FROM vip_subscriptions WHERE user_id=?", (user_id,)
                ).fetchone()
            return row

    def expire_vips(self) -> list[sqlite3.Row]:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM vip_subscriptions WHERE status='active' AND end_at<=?", (now,)
            ).fetchall()
            if rows:
                conn.executemany(
                    "UPDATE vip_subscriptions SET status='expired' WHERE user_id=?",
                    [(r["user_id"],) for r in rows],
                )
            return rows

    def get_expiring_vips(self, hours: int = 24) -> list[sqlite3.Row]:
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        until = now + timedelta(hours=hours)
        with self._lock, self._connect() as conn:
            return conn.execute(
                """SELECT * FROM vip_subscriptions WHERE status='active' AND notified_expiry=0
                   AND end_at>? AND end_at<=?""",
                (now.isoformat(), until.isoformat()),
            ).fetchall()

    def mark_vip_expiry_notified(self, user_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE vip_subscriptions SET notified_expiry=1 WHERE user_id=?", (user_id,))

    def create_trade(self, **kwargs: Any) -> int:
        fields = [
            "symbol", "direction", "entry", "sl", "tp1", "tp2", "rr", "risk_percent",
            "created_at", "entry_message_id", "teaser_message_id", "notes"
        ]
        values = [kwargs.get(f) for f in fields]
        if values[8] is None:
            values[8] = self.now()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO trades({','.join(fields)}) VALUES({','.join('?' for _ in fields)})",
                values,
            )
            return int(cur.lastrowid)

    def get_trade(self, trade_id: int) -> Optional[sqlite3.Row]:
        with self._lock, self._connect() as conn:
            return conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()

    def get_open_trades(self) -> list[sqlite3.Row]:
        with self._lock, self._connect() as conn:
            return conn.execute("SELECT * FROM trades WHERE status='OPEN' ORDER BY id").fetchall()

    def get_open_trade_for_symbol(self, symbol: str) -> Optional[sqlite3.Row]:
        with self._lock, self._connect() as conn:
            return conn.execute(
                "SELECT * FROM trades WHERE symbol=? AND status='OPEN' ORDER BY id DESC LIMIT 1", (symbol,)
            ).fetchone()

    def recent_signal_exists(self, symbol: str, minutes: int) -> bool:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM trades WHERE symbol=? AND created_at>=? ORDER BY id DESC LIMIT 1",
                (symbol, cutoff.isoformat()),
            ).fetchone()
            return row is not None

    def update_trade(self, trade_id: int, **kwargs: Any) -> None:
        if not kwargs:
            return
        allowed = {
            "status", "tp1_hit", "tp2_hit", "breakeven_alert_sent", "invalidation_alert_sent",
            "closed_at", "result_message_id", "last_price", "pnl_pips", "notes"
        }
        kwargs = {k: v for k, v in kwargs.items() if k in allowed}
        if not kwargs:
            return
        assignments = ", ".join(f"{k}=?" for k in kwargs)
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE trades SET {assignments} WHERE id=?", [*kwargs.values(), trade_id]
            )

    def log_event(self, event_type: str, message: str = "", trade_id: int | None = None, user_id: int | None = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO events(event_type,trade_id,user_id,message,created_at) VALUES(?,?,?,?,?)",
                (event_type, trade_id, user_id, message, self.now()),
            )

    def stats(self) -> dict[str, int | float]:
        with self._lock, self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) c FROM trades").fetchone()["c"]
            open_ = conn.execute("SELECT COUNT(*) c FROM trades WHERE status='OPEN'").fetchone()["c"]
            wins = conn.execute("SELECT COUNT(*) c FROM trades WHERE status='TP2'").fetchone()["c"]
            tp1 = conn.execute("SELECT COUNT(*) c FROM trades WHERE tp1_hit=1").fetchone()["c"]
            losses = conn.execute("SELECT COUNT(*) c FROM trades WHERE status='SL'").fetchone()["c"]
            invalid = conn.execute("SELECT COUNT(*) c FROM trades WHERE status='INVALIDATED'").fetchone()["c"]
            vip = conn.execute("SELECT COUNT(*) c FROM vip_subscriptions WHERE status='active'").fetchone()["c"]
            pips = conn.execute("SELECT COALESCE(SUM(pnl_pips),0) p FROM trades WHERE pnl_pips IS NOT NULL").fetchone()["p"]
            return {"trades": total, "open": open_, "tp1": tp1, "tp2": wins, "sl": losses, "invalidated": invalid, "vip": vip, "pips": pips}

    def export_trades_csv(self) -> bytes:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM trades ORDER BY id").fetchall()
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(rows[0].keys() if rows else ["id"])
            for row in rows:
                writer.writerow(list(row))
            return output.getvalue().encode("utf-8")
