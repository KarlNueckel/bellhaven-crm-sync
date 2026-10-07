"""SQLite schema and connection helper."""
import sqlite3

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS site_locations (
    slug           TEXT PRIMARY KEY,
    url            TEXT NOT NULL,
    name           TEXT NOT NULL,
    street         TEXT,
    city           TEXT,
    state          TEXT,
    zip            TEXT,
    care_offerings TEXT,          -- JSON list of labels exactly as shown on the site
    administrator  TEXT,
    phone          TEXT,
    found_on       TEXT,          -- JSON list of pages that linked to this community
    scraped_at     TEXT NOT NULL
);

-- Every CRM request/response, for the audit trail.
CREATE TABLE IF NOT EXISTS api_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    method        TEXT NOT NULL,
    url           TEXT NOT NULL,
    request_body  TEXT,
    status        INTEGER,
    response_body TEXT
);

-- One row per proposed change. status: pending | approved | rejected | failed
CREATE TABLE IF NOT EXISTS proposals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT UNIQUE NOT NULL,   -- hash of type + account + site + proposed values
    type        TEXT NOT NULL,
    title       TEXT NOT NULL,
    account_id  TEXT,
    site_slug   TEXT,
    payload     TEXT NOT NULL,          -- JSON: proposed values, API actions, evidence, snapshots
    status      TEXT NOT NULL,
    result      TEXT,
    created_at  TEXT NOT NULL,
    decided_at  TEXT
);

-- Reviewer decisions for sites the rules can't resolve (e.g. which duplicate survives).
CREATE TABLE IF NOT EXISTS decisions (
    site_slug   TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL,
    decided_at  TEXT NOT NULL
);
"""


def connect(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
