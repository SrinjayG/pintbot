"""SQLite storage. One file: data/pintbot.db (swap for Postgres later if you want)."""
from __future__ import annotations
import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id            TEXT PRIMARY KEY,
    sender_id     TEXT NOT NULL,
    sender_name   TEXT,
    ts            INTEGER NOT NULL,
    text          TEXT,
    photo         TEXT,
    photo_hash    TEXT,
    quoted_id     TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
        -- pending | counted | not_drink | duplicate_photo | needs_review | held | corrected | error
    retries       INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    extraction    TEXT,      -- raw JSON from Claude, kept for debugging and evals
    processed_at  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status);
CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts);

CREATE TABLE IF NOT EXISTS drinks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id    TEXT NOT NULL REFERENCES messages(id),
    sender_id     TEXT NOT NULL,
    sender_name   TEXT,
    ts            INTEGER NOT NULL,
    drink_type    TEXT,
    name          TEXT,
    abv           REAL,
    abv_source    TEXT,      -- post | cache | search | NULL
    quantity      INTEGER,
    non_alcoholic INTEGER,
    points        REAL NOT NULL,
    voided        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_drinks_ts ON drinks(ts);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS beers (
    name_key       TEXT PRIMARY KEY,   -- normalised name as people write it
    canonical_name TEXT,
    abv            REAL,
    found          INTEGER NOT NULL,
    source_url     TEXT,
    looked_up_at   INTEGER NOT NULL
);
"""


def connect(path=None) -> sqlite3.Connection:
    p = path or config.DB_PATH
    if path is None:
        config.DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn) -> None:
    """Add columns introduced after a database was first created."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(drinks)")}
    if "abv_source" not in cols:
        conn.execute("ALTER TABLE drinks ADD COLUMN abv_source TEXT")
        conn.commit()


def get_meta(conn, key):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn, key, value):
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
