"""
Tiny synchronous SQLite data layer for Anime Index.

No ORM on purpose — the schema is small enough that plain sqlite3 keeps
this easy to read and easy to deploy (a single file database, no extra
service to run on Render/Koyeb). Every function opens and closes its own
connection, which is safe across threads and keeps things simple for a
low-traffic bot + mini app.
"""

import json
import os
import sqlite3
import time
from contextlib import contextmanager

from config import Config

SCHEMA = """
CREATE TABLE IF NOT EXISTS anime (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    year INTEGER,
    poster_url TEXT,
    banner_url TEXT,
    description TEXT,
    genres TEXT NOT NULL DEFAULT '[]',
    rating REAL,
    join_link TEXT,
    added_by INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(source, source_id)
);

CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    role TEXT NOT NULL DEFAULT 'member',
    access TEXT NOT NULL DEFAULT 'active',
    registered_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anime_title TEXT NOT NULL,
    requested_by INTEGER,
    requested_by_name TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anime_id INTEGER,
    anime_title TEXT,
    reason TEXT NOT NULL,
    details TEXT,
    reported_by INTEGER,
    reported_by_name TEXT,
    created_at REAL NOT NULL
);
"""


@contextmanager
def get_conn():
    os.makedirs(os.path.dirname(Config.DATABASE_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Anime catalog
# ---------------------------------------------------------------------------

def _row_to_anime(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["genres"] = json.loads(d.get("genres") or "[]")
    d["available"] = bool(d.get("join_link"))
    return d


def upsert_anime(details: dict, added_by: int | None = None) -> int:
    """Insert a new catalog entry from a normalized source dict, or update
    the existing one if this (source, source_id) was already posted."""
    now = time.time()
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT id FROM anime WHERE source = ? AND source_id = ?",
            (details["source"], str(details["source_id"])),
        )
        existing = cur.fetchone()
        if existing:
            conn.execute(
                """UPDATE anime SET title=?, year=?, poster_url=?, banner_url=?,
                       description=?, genres=?, rating=?, updated_at=?
                   WHERE id=?""",
                (
                    details["title"], details.get("year"), details.get("poster_url"),
                    details.get("banner_url"), details.get("description"),
                    json.dumps(details.get("genres", [])), details.get("rating"),
                    now, existing["id"],
                ),
            )
            return existing["id"]

        cur = conn.execute(
            """INSERT INTO anime
                   (source, source_id, title, year, poster_url, banner_url,
                    description, genres, rating, join_link, added_by, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                details["source"], str(details["source_id"]), details["title"],
                details.get("year"), details.get("poster_url"), details.get("banner_url"),
                details.get("description"), json.dumps(details.get("genres", [])),
                details.get("rating"), None, added_by, now, now,
            ),
        )
        return cur.lastrowid


def delete_anime(anime_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM anime WHERE id = ?", (anime_id,))


def get_anime(anime_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM anime WHERE id = ?", (anime_id,)).fetchone()
        return _row_to_anime(row) if row else None


def list_available() -> list[dict]:
    """Only posts that currently have a join link set."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM anime WHERE join_link IS NOT NULL AND join_link != '' ORDER BY title COLLATE NOCASE"
        ).fetchall()
        return [_row_to_anime(r) for r in rows]


def search_local(query: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM anime WHERE title LIKE ? ORDER BY title COLLATE NOCASE",
            (f"%{query}%",),
        ).fetchall()
        return [_row_to_anime(r) for r in rows]


def update_link(anime_id: int, link: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE anime SET join_link = ?, updated_at = ? WHERE id = ?",
            (link or None, time.time(), anime_id),
        )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_or_create_user(telegram_id: int, username: str | None, first_name: str | None,
                        is_admin: bool) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        role = "admin" if is_admin else "member"
        if row:
            conn.execute(
                "UPDATE users SET username=?, first_name=?, role=? WHERE telegram_id=?",
                (username, first_name, role, telegram_id),
            )
            data = dict(row)
            data["username"] = username
            data["first_name"] = first_name
            data["role"] = role
            return data

        now = time.time()
        conn.execute(
            "INSERT INTO users (telegram_id, username, first_name, role, access, registered_at) VALUES (?,?,?,?,?,?)",
            (telegram_id, username, first_name, role, "active", now),
        )
        return {
            "telegram_id": telegram_id, "username": username, "first_name": first_name,
            "role": role, "access": "active", "registered_at": now,
        }


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

def create_request(anime_title: str, requested_by: int | None, requested_by_name: str | None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO requests (anime_title, requested_by, requested_by_name, status, created_at) VALUES (?,?,?,?,?)",
            (anime_title, requested_by, requested_by_name, "pending", time.time()),
        )
        return cur.lastrowid


def get_request(request_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
        return dict(row) if row else None


def update_request_status(request_id: int, status: str):
    with get_conn() as conn:
        conn.execute("UPDATE requests SET status = ? WHERE id = ?", (status, request_id))


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def create_report(anime_id: int | None, anime_title: str, reason: str, details: str,
                   reported_by: int | None, reported_by_name: str | None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO reports
                   (anime_id, anime_title, reason, details, reported_by, reported_by_name, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (anime_id, anime_title, reason, details, reported_by, reported_by_name, time.time()),
        )
        return cur.lastrowid
