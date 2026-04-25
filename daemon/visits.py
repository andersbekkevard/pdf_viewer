"""Visit tracking — SQLite log of every cache hit in /view.

One row per visit. Aggregates computed at query time; at personal-use
volume (single-digit visits/day) the events table stays well under 1MB
for years, so maintaining a rollup is unnecessary overhead.

LRU eviction is deliberately NOT built on top of this (PLAN §3:
"Deferred until cache bloat becomes real"). This is observability only.
"""
from __future__ import annotations

import pathlib
import sqlite3
import time
from typing import Literal

DB_PATH = pathlib.Path.home() / ".cache" / "pdf_viewer" / "visits.db"
SESSION_WINDOW_SEC = 15 * 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
    hash TEXT    NOT NULL,
    ts   INTEGER NOT NULL,
    kind TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_visits_hash ON visits(hash);
CREATE INDEX IF NOT EXISTS idx_visits_ts   ON visits(ts);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def record(hash_: str, kind: Literal["url", "path"]) -> None:
    """Insert one visit row. Called from a BackgroundTask — must never raise."""
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO visits(hash, ts, kind) VALUES(?, ?, ?)",
                (hash_, int(time.time()), kind),
            )
    except sqlite3.Error:
        pass


def summary(top_n: int = 20) -> dict:
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
        unique = conn.execute("SELECT COUNT(DISTINCT hash) FROM visits").fetchone()[0]
        first_last = conn.execute(
            "SELECT MIN(ts), MAX(ts) FROM visits"
        ).fetchone()
        top = conn.execute(
            """
            SELECT hash, COUNT(*) AS n, MIN(ts) AS first_seen, MAX(ts) AS last_seen
            FROM visits
            GROUP BY hash
            ORDER BY n DESC, last_seen DESC
            LIMIT ?
            """,
            (top_n,),
        ).fetchall()
    return {
        "total_visits": total,
        "unique_docs": unique,
        "first_visit": first_last[0],
        "last_visit": first_last[1],
        "top": [
            {"hash": h, "count": n, "first_seen": f, "last_seen": l}
            for h, n, f, l in top
        ],
    }


def all_counts() -> dict[str, dict]:
    """hash → {count, last_seen}. One per doc. Empty on DB error.

    Used by /library to rank cache entries by recency. Kept in visits.py
    so the SQL stays next to the schema that defines it.
    """
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT hash, COUNT(*), MAX(ts) FROM visits GROUP BY hash"
            ).fetchall()
        return {h: {"count": n, "last_seen": t} for h, n, t in rows}
    except sqlite3.Error:
        return {}


def _zoxide_multiplier(age_sec: int) -> float:
    """zoxide-style query-time recency multiplier."""
    if age_sec < 3600:
        return 4.0
    if age_sec < 86400:
        return 2.0
    if age_sec < 604800:
        return 0.5
    return 0.25


def all_frecency(now: int | None = None) -> dict[str, dict]:
    """hash → sessionized zoxide-style frecency metrics.

    Rank is one effective open per 15-minute wall-clock bucket. Raw visits
    stay available for diagnostics/display, but reloads and browser restores
    inside the same bucket do not inflate the score.
    """
    if now is None:
        now = int(time.time())
    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    hash,
                    COUNT(*) AS raw_count,
                    COUNT(DISTINCT CAST(ts / ? AS INTEGER)) AS rank,
                    MAX(ts) AS last_seen
                FROM visits
                GROUP BY hash
                """,
                (SESSION_WINDOW_SEC,),
            ).fetchall()
    except sqlite3.Error:
        return {}

    out = {}
    for hash_, raw_count, rank, last_seen in rows:
        age_sec = max(0, now - last_seen)
        multiplier = _zoxide_multiplier(age_sec)
        out[hash_] = {
            "raw_count": raw_count,
            "rank": rank,
            "last_seen": last_seen,
            "age_multiplier": multiplier,
            "frecency_score": rank * multiplier,
        }
    return out


def recent(limit: int = 100) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT hash, ts, kind FROM visits ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"hash": h, "ts": t, "kind": k} for h, t, k in rows]
