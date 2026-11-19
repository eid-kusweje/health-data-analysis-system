"""
db.py - SQLite persistence layer.

SQLite is the test database and the built-in backup database for this
project (see README: "Database strategy"). All SQL is kept in this one
module and uses only standard SQL, so the application data can be moved
to PostgreSQL later by re-implementing the functions in this file -
the rest of the application does not contain SQL.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import generate_password_hash, check_password_hash

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'analyst'
                  CHECK (role IN ('admin', 'analyst', 'viewer')),
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS datasets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    stored_path       TEXT NOT NULL,
    file_type         TEXT NOT NULL,
    row_count         INTEGER NOT NULL DEFAULT 0,
    col_count         INTEGER NOT NULL DEFAULT 0,
    mapping_json      TEXT NOT NULL DEFAULT '{}',
    description       TEXT DEFAULT '',
    is_demo           INTEGER NOT NULL DEFAULT 0,
    owner_id          INTEGER REFERENCES users(id),
    uploaded_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_tokens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL UNIQUE,
    expires_at INTEGER NOT NULL,
    revoked    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id),
    action     TEXT NOT NULL,
    detail     TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | Path) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


# --- users -------------------------------------------------------------------
def create_user(db_path, name, email, password, role="analyst") -> int:
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, role, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, email.strip().lower(), generate_password_hash(password),
             role, _now()),
        )
        return cur.lastrowid


def get_user_by_email(db_path, email):
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?",
                           (email.strip().lower(),)).fetchone()
    return dict(row) if row else None


def get_user(db_path, user_id):
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def verify_user(db_path, email, password):
    user = get_user_by_email(db_path, email)
    if not user or not user["is_active"]:
        return None
    if not check_password_hash(user["password_hash"], password):
        return None
    return user


def list_users(db_path):
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name, email, role, is_active, created_at "
            "FROM users ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def set_user_active(db_path, user_id, active: bool):
    with connect(db_path) as conn:
        conn.execute("UPDATE users SET is_active = ? WHERE id = ?",
                     (1 if active else 0, user_id))


def public_user(user: dict) -> dict:
    return {k: user[k] for k in ("id", "name", "email", "role") if k in user}


# --- API tokens (Bearer auth) --------------------------------------------------
# Login also returns a random Bearer token whose SHA-256 hash is stored here.
# The web page sends it as an Authorization header on every API call, so the
# app keeps working where session COOKIES are blocked - notably when the
# dashboard is embedded in a cross-site iframe (e.g. a hosted live preview),
# where browsers refuse third-party cookies. Only hashes are stored, tokens
# expire, and logout revokes the presented token.
TOKEN_TTL_SECONDS = 7 * 24 * 3600


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_auth_token(db_path, user_id, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    raw = secrets.token_urlsafe(32)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO auth_tokens (user_id, token_hash, expires_at, created_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, _hash_token(raw), int(time.time()) + ttl_seconds, _now()))
    return raw


def get_user_by_token(db_path, raw):
    if not raw:
        return None
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT u.* FROM auth_tokens t JOIN users u ON u.id = t.user_id "
            "WHERE t.token_hash = ? AND t.revoked = 0 AND t.expires_at > ?",
            (_hash_token(raw), int(time.time()))).fetchone()
    return dict(row) if row else None


def revoke_token(db_path, raw) -> None:
    if raw:
        with connect(db_path) as conn:
            conn.execute("UPDATE auth_tokens SET revoked = 1 WHERE token_hash = ?",
                         (_hash_token(raw),))


# --- datasets ------------------------------------------------------------------
def add_dataset(db_path, *, name, original_filename, stored_path, file_type,
                row_count, col_count, mapping, owner_id, is_demo=False,
                description="") -> int:
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO datasets (name, original_filename, stored_path, file_type,"
            " row_count, col_count, mapping_json, description, is_demo, owner_id,"
            " uploaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, original_filename, str(stored_path), file_type, row_count,
             col_count, json.dumps(mapping), description, 1 if is_demo else 0,
             owner_id, _now()),
        )
        return cur.lastrowid


def list_datasets(db_path):
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT d.*, u.name AS owner_name FROM datasets d "
            "LEFT JOIN users u ON u.id = d.owner_id ORDER BY d.id DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["mapping"] = json.loads(d.pop("mapping_json") or "{}")
        d["is_demo"] = bool(d["is_demo"])
        d.pop("stored_path", None)
        out.append(d)
    return out


def get_dataset(db_path, dataset_id):
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM datasets WHERE id = ?",
                           (dataset_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["mapping"] = json.loads(d.pop("mapping_json") or "{}")
    d["is_demo"] = bool(d["is_demo"])
    return d


def delete_dataset(db_path, dataset_id):
    with connect(db_path) as conn:
        conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))


# --- audit ----------------------------------------------------------------------
def log_action(db_path, user_id, action, detail=""):
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO audit_log (user_id, action, detail, created_at) "
            "VALUES (?, ?, ?, ?)", (user_id, action, detail, _now()))


def list_audit(db_path, limit=100):
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT a.*, u.email AS user_email FROM audit_log a "
            "LEFT JOIN users u ON u.id = a.user_id "
            "ORDER BY a.id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
