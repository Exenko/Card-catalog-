"""SQLite storage layer. Raw sqlite3 with parameterised queries -- no ORM, so the
schema below is the whole truth about the data model."""
import os
import sqlite3
import secrets
from contextlib import contextmanager

DATA_DIR = os.environ.get("CARDCATALOG_DATA", "/data")
DB_PATH = os.path.join(DATA_DIR, "cardcatalog.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS artists (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    shop_name   TEXT DEFAULT '',
    handle      TEXT DEFAULT '',
    met_at      TEXT DEFAULT '',   -- convention where you picked up the card
    met_on      TEXT DEFAULT '',   -- ISO date, free text ok
    booth       TEXT DEFAULT '',
    interest    INTEGER DEFAULT 2, -- 1 = must buy, 2 = like, 3 = maybe
    notes       TEXT DEFAULT '',
    card_front  TEXT DEFAULT '',   -- filename under uploads/
    card_back   TEXT DEFAULT '',
    ocr_text    TEXT DEFAULT '',
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tags (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE,
    kind  TEXT DEFAULT 'general'  -- general | medium | fandom | vibe | status
);

CREATE TABLE IF NOT EXISTS artist_tags (
    artist_id INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    tag_id    INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (artist_id, tag_id)
);

CREATE TABLE IF NOT EXISTS links (
    id        INTEGER PRIMARY KEY,
    artist_id INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    label     TEXT DEFAULT '',
    url       TEXT NOT NULL,
    sort      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS wishlist_items (
    id         INTEGER PRIMARY KEY,
    artist_id  INTEGER NOT NULL REFERENCES artists(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    url        TEXT DEFAULT '',
    price      REAL,
    priority   INTEGER DEFAULT 2,      -- 1 = grail, 2 = want, 3 = someday
    status     TEXT DEFAULT 'want',    -- want | bought | sold_out | passed
    target_con TEXT DEFAULT '',
    notes      TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_artist ON wishlist_items(artist_id);
CREATE INDEX IF NOT EXISTS idx_items_status ON wishlist_items(status);
CREATE INDEX IF NOT EXISTS idx_links_artist ON links(artist_id);
"""

STATUSES = ["want", "bought", "sold_out", "passed"]
STATUS_LABELS = {
    "want": "Want", "bought": "Bought",
    "sold_out": "Sold out", "passed": "Passed",
}
INTEREST_LABELS = {1: "Must buy", 2: "Like", 3: "Maybe"}
PRIORITY_LABELS = {1: "Grail", 2: "Want", 3: "Someday"}


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)
        cur = conn.execute("SELECT value FROM settings WHERE key='share_token'")
        if cur.fetchone() is None:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('share_token', ?)",
                (secrets.token_urlsafe(12),),
            )


def get_setting(conn, key, default=""):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def tag_ids_for_names(conn, names, kind="general"):
    """Create any tags that don't exist yet, return their ids."""
    ids = []
    for raw in names:
        name = raw.strip().lower()
        if not name:
            continue
        conn.execute("INSERT OR IGNORE INTO tags (name, kind) VALUES (?, ?)", (name, kind))
        row = conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
        ids.append(row["id"])
    return ids


def set_artist_tags(conn, artist_id, names):
    conn.execute("DELETE FROM artist_tags WHERE artist_id=?", (artist_id,))
    for tag_id in tag_ids_for_names(conn, names):
        conn.execute(
            "INSERT OR IGNORE INTO artist_tags (artist_id, tag_id) VALUES (?, ?)",
            (artist_id, tag_id),
        )


def set_artist_links(conn, artist_id, pairs):
    """pairs: iterable of (label, url)."""
    conn.execute("DELETE FROM links WHERE artist_id=?", (artist_id,))
    for i, (label, url) in enumerate(pairs):
        url = (url or "").strip()
        if not url:
            continue
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        conn.execute(
            "INSERT INTO links (artist_id, label, url, sort) VALUES (?, ?, ?, ?)",
            (artist_id, (label or "").strip(), url, i),
        )


def artist_tags(conn, artist_id):
    return [r["name"] for r in conn.execute(
        "SELECT t.name FROM tags t JOIN artist_tags at ON at.tag_id=t.id "
        "WHERE at.artist_id=? ORDER BY t.name", (artist_id,))]


def artist_links(conn, artist_id):
    return conn.execute(
        "SELECT * FROM links WHERE artist_id=? ORDER BY sort, id", (artist_id,)
    ).fetchall()


def all_tags(conn):
    return conn.execute(
        "SELECT t.id, t.name, t.kind, COUNT(at.artist_id) AS n "
        "FROM tags t LEFT JOIN artist_tags at ON at.tag_id=t.id "
        "GROUP BY t.id ORDER BY n DESC, t.name"
    ).fetchall()
