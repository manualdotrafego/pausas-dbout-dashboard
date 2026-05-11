"""SQLite wrapper para eventos de pausa/ativação."""
from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime
from typing import Iterator

DB_PATH = Path(__file__).parent / "data" / "pausas.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE NOT NULL,
    event_type TEXT NOT NULL,       -- 'pausar' | 'ativar'
    timestamp TEXT NOT NULL,         -- ISO 8601 UTC
    author TEXT NOT NULL,
    author_id TEXT,
    unit_name TEXT NOT NULL,
    unit_key TEXT NOT NULL,
    reason TEXT,
    mentions_json TEXT NOT NULL DEFAULT '[]',
    raw_content TEXT,
    channel_id TEXT,
    channel_name TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_unit_key ON events(unit_key);
CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events(event_type, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp);
"""


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    with get_conn() as con:
        con.executescript(SCHEMA)


def upsert_event(
    *,
    message_id: str,
    event_type: str,
    timestamp: datetime,
    author: str,
    author_id: str | None,
    unit_name: str,
    unit_key: str,
    reason: str,
    mentions: list[str],
    raw_content: str,
    channel_id: str | None,
    channel_name: str | None,
) -> bool:
    """Insert or update event. Returns True if newly inserted."""
    with get_conn() as con:
        cur = con.execute(
            """
            INSERT INTO events
                (message_id, event_type, timestamp, author, author_id, unit_name, unit_key,
                 reason, mentions_json, raw_content, channel_id, channel_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                event_type = excluded.event_type,
                unit_name = excluded.unit_name,
                unit_key = excluded.unit_key,
                reason = excluded.reason,
                mentions_json = excluded.mentions_json,
                raw_content = excluded.raw_content
            """,
            (
                message_id,
                event_type,
                timestamp.isoformat(),
                author,
                author_id,
                unit_name,
                unit_key,
                reason,
                json.dumps(mentions, ensure_ascii=False),
                raw_content,
                channel_id,
                channel_name,
            ),
        )
        return cur.rowcount > 0


def all_events() -> list[dict]:
    with get_conn() as con:
        rows = con.execute(
            "SELECT * FROM events ORDER BY timestamp DESC"
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["mentions"] = json.loads(d.pop("mentions_json") or "[]")
        out.append(d)
    return out


def latest_event_timestamp() -> datetime | None:
    """Timestamp do evento mais recente no DB (para catch-up no reconnect)."""
    with get_conn() as con:
        row = con.execute("SELECT MAX(timestamp) AS ts FROM events").fetchone()
    if not row or not row["ts"]:
        return None
    try:
        return datetime.fromisoformat(row["ts"])
    except Exception:
        return None


def latest_event_per_unit() -> dict[str, dict]:
    """Returns the most recent event for each unit_key."""
    with get_conn() as con:
        rows = con.execute(
            """
            SELECT e.* FROM events e
            JOIN (
                SELECT unit_key, MAX(timestamp) AS max_ts
                FROM events GROUP BY unit_key
            ) m ON m.unit_key = e.unit_key AND m.max_ts = e.timestamp
            """
        ).fetchall()
    out = {}
    for r in rows:
        d = dict(r)
        d["mentions"] = json.loads(d.pop("mentions_json") or "[]")
        out[d["unit_key"]] = d
    return out
