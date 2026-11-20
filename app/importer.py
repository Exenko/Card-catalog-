"""CSV import from an existing spreadsheet.

Nobody's con-card sheet has the same columns, so this guesses a mapping from the
header row, shows it for correction, and only then writes. Rows that name an
artist already present are merged, not duplicated.
"""
import csv
import io
import re

from . import db

# Internal field -> header substrings that probably mean it.
FIELD_HINTS = {
    "name":       ["artist", "name", "who", "creator", "maker"],
    "shop_name":  ["shop", "store", "brand", "business", "company"],
    "handle":     ["handle", "username", "user name", "ig", "insta", "social", "@"],
    "met_at":     ["con", "convention", "event", "show", "met at", "where", "venue"],
    "met_on":     ["date", "year", "when", "met on"],
    "booth":      ["booth", "table", "stand", "aa", "artist alley"],
    "tags":       ["tag", "tags", "category", "categories", "type", "medium", "keywords", "genre", "fandom"],
    "notes":      ["note", "notes", "comment", "comments", "detail", "description", "misc"],
    "interest":   ["interest", "rating", "rank", "tier", "stars"],
    "item_title": ["item", "piece", "want", "wishlist", "product", "wish list", "title"],
    "item_url":   ["link", "url", "website", "site", "shop link", "web"],
    "item_price": ["price", "cost", "$", "amount", "usd"],
    "item_status":["status", "bought", "purchased", "owned", "state"],
    "item_notes": ["item note", "piece note"],
}

TARGET_FIELDS = list(FIELD_HINTS.keys())

FIELD_LABELS = {
    "name": "Artist name", "shop_name": "Shop name", "handle": "Handle",
    "met_at": "Met at (convention)", "met_on": "Met on (date)", "booth": "Booth",
    "tags": "Tags", "notes": "Notes", "interest": "Interest level",
    "item_title": "Wishlist item", "item_url": "Link", "item_price": "Price",
    "item_status": "Item status", "item_notes": "Item notes",
}

STATUS_WORDS = {
    "bought": "bought", "purchased": "bought", "have": "bought", "owned": "bought",
    "yes": "bought", "y": "bought", "done": "bought", "got it": "bought",
    "sold out": "sold_out", "soldout": "sold_out", "unavailable": "sold_out",
    "gone": "sold_out", "discontinued": "sold_out",
    "passed": "passed", "no": "passed", "skip": "passed", "skipped": "passed",
    "want": "want", "wishlist": "want", "pending": "want", "todo": "want",
}


def sniff(content_bytes):
    """Decode, parse and guess a column mapping. Returns (headers, rows, mapping)."""
    text = content_bytes.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    if not rows:
        return [], [], {}
    headers = [(h or "").strip() for h in rows[0]]
    body = rows[1:]
    return headers, body, guess_mapping(headers)


def guess_mapping(headers):
    """header index -> internal field name (or '' to ignore)."""
    mapping = {}
    taken = set()
    scored = []
    for idx, header in enumerate(headers):
        low = re.sub(r"[^a-z0-9@$ ]", " ", header.lower()).strip()
        if not low:
            continue
        for field, hints in FIELD_HINTS.items():
            for hint in hints:
                if low == hint:
                    scored.append((100 + len(hint), idx, field))
                elif re.search(rf"\b{re.escape(hint)}\b", low):
                    scored.append((50 + len(hint), idx, field))
                elif hint in low:
                    scored.append((20 + len(hint), idx, field))
    # Highest-confidence pairings first; one column per field, one field per column.
    for _score, idx, field in sorted(scored, key=lambda s: -s[0]):
        if idx in mapping or field in taken:
            continue
        mapping[idx] = field
        taken.add(field)
    if not taken & {"name"} and headers:
        mapping[0] = "name"  # first column is nearly always the artist
    return mapping


def _price(raw):
    if raw is None:
        return None
    cleaned = re.sub(r"[^0-9.]", "", str(raw))
    if not cleaned or cleaned == ".":
        return None
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def _status(raw):
    low = (raw or "").strip().lower()
    if not low:
        return "want"
    if low in STATUS_WORDS:
        return STATUS_WORDS[low]
    for word, status in STATUS_WORDS.items():
        if word in low:
            return status
    return "want"


def _interest(raw):
    low = (raw or "").strip().lower()
    if not low:
        return 2
    stars = low.count("*") + low.count("★")
    if stars:
        return 1 if stars >= 3 else (2 if stars == 2 else 3)
    m = re.search(r"\d+", low)
    if m:
        n = int(m.group())
        if n >= 4:
            return 1
        return {0: 3, 1: 3, 2: 2, 3: 1}.get(n, 2)
    if any(w in low for w in ("must", "high", "grail", "top", "love")):
        return 1
    if any(w in low for w in ("maybe", "low", "someday")):
        return 3
    return 2


def _split_tags(raw):
    if not raw:
        return []
    parts = re.split(r"[,;/|]|\s{2,}", raw)
    return [p.strip().lower() for p in parts if p.strip()]


def do_import(conn, headers, rows, mapping, dry_run=False):
    """Apply a confirmed mapping. Returns a summary dict."""
    # mapping keys may arrive as strings from a form post.
    mapping = {int(k): v for k, v in mapping.items() if v}
    by_field = {}
    for idx, field in mapping.items():
        by_field.setdefault(field, idx)

    def cell(row, field):
        idx = by_field.get(field)
        if idx is None or idx >= len(row):
            return ""
        return (row[idx] or "").strip()

    summary = {
        "artists_created": 0, "artists_merged": 0,
        "items_created": 0, "items_duplicate": 0, "links_created": 0,
        "rows_skipped": 0, "skipped_detail": [], "tags_seen": set(),
    }
    # name (lowered) -> artist id, so repeated rows for one artist collapse.
    seen = {}
    for row_no, row in enumerate(rows, start=2):
        name = cell(row, "name")
        if not name:
            summary["rows_skipped"] += 1
            if len(summary["skipped_detail"]) < 8:
                summary["skipped_detail"].append(f"row {row_no}: no artist name")
            continue

        key = name.lower()
        artist_id = seen.get(key)
        if artist_id is None:
            existing = conn.execute(
                "SELECT id FROM artists WHERE lower(name)=?", (key,)
            ).fetchone()
            if existing:
                artist_id = existing["id"]
                summary["artists_merged"] += 1
            else:
                cur = conn.execute(
                    "INSERT INTO artists (name, shop_name, handle, met_at, met_on, "
                    "booth, interest, notes) VALUES (?,?,?,?,?,?,?,?)",
                    (name, cell(row, "shop_name"), cell(row, "handle").lstrip("@"),
                     cell(row, "met_at"), cell(row, "met_on"), cell(row, "booth"),
                     _interest(cell(row, "interest")), cell(row, "notes")),
                )
                artist_id = cur.lastrowid
                summary["artists_created"] += 1
            seen[key] = artist_id

        tags = _split_tags(cell(row, "tags"))
        if tags:
            summary["tags_seen"].update(tags)
            for tag_id in db.tag_ids_for_names(conn, tags):
                conn.execute(
                    "INSERT OR IGNORE INTO artist_tags (artist_id, tag_id) VALUES (?,?)",
                    (artist_id, tag_id),
                )

        url = cell(row, "item_url")
        title = cell(row, "item_title")
        price = _price(cell(row, "item_price"))
        status_raw = cell(row, "item_status")
        item_notes = cell(row, "item_notes")

        if title or price is not None or (url and status_raw):
            item_title = title or f"{name} - untitled"
            # Re-importing the same sheet must not double the wish list, so an
            # item this artist already has (same title) is left alone.
            dupe = conn.execute(
                "SELECT 1 FROM wishlist_items WHERE artist_id=? AND lower(title)=?",
                (artist_id, item_title.lower()),
            ).fetchone()
            if dupe:
                summary["items_duplicate"] += 1
            else:
                conn.execute(
                    "INSERT INTO wishlist_items (artist_id, title, url, price, status, notes) "
                    "VALUES (?,?,?,?,?,?)",
                    (artist_id, item_title, url, price,
                     _status(status_raw), item_notes),
                )
                summary["items_created"] += 1
        elif url:
            # A bare link with no item attached is the artist's shop link.
            already = conn.execute(
                "SELECT 1 FROM links WHERE artist_id=? AND url=?", (artist_id, url)
            ).fetchone()
            if not already:
                full = url if url.startswith(("http://", "https://")) else "https://" + url
                from .ocr import _label_for
                conn.execute(
                    "INSERT INTO links (artist_id, label, url) VALUES (?,?,?)",
                    (artist_id, _label_for(full), full),
                )
                summary["links_created"] += 1

    summary["tags_seen"] = sorted(summary["tags_seen"])
    if dry_run:
        conn.rollback()
    return summary
