"""CSV exports. Three shapes, because they serve different jobs:

  sheet.csv       one flat row per wishlist item -- drop straight into Sheets
  artists.csv     one row per artist, tags and links collapsed
  wishlist.csv    the public wish list, trimmed to what a gift-giver needs
  mywishlist.csv  name / url / price / notes, the shape generic wishlist sites eat
"""
import csv
import io


def _write(headers, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(headers)
    w.writerows(rows)
    return buf.getvalue()


def _tags(conn, artist_id):
    return ", ".join(r["name"] for r in conn.execute(
        "SELECT t.name FROM tags t JOIN artist_tags at ON at.tag_id=t.id "
        "WHERE at.artist_id=? ORDER BY t.name", (artist_id,)))


def _links(conn, artist_id):
    return " | ".join(
        f"{r['label']}: {r['url']}" if r["label"] else r["url"]
        for r in conn.execute(
            "SELECT label, url FROM links WHERE artist_id=? ORDER BY sort, id",
            (artist_id,)))


def sheet_csv(conn):
    """Flat artist x item join -- the Google Sheets round-trip format.
    Re-importing this file reproduces the library, so it doubles as a backup."""
    headers = ["Artist", "Shop", "Handle", "Tags", "Met at", "Met on", "Booth",
               "Interest", "Artist notes", "Links",
               "Item", "Link", "Price", "Status", "Priority", "Target con", "Item notes"]
    rows = []
    for a in conn.execute("SELECT * FROM artists ORDER BY name COLLATE NOCASE"):
        base = [a["name"], a["shop_name"], ("@" + a["handle"]) if a["handle"] else "",
                _tags(conn, a["id"]), a["met_at"], a["met_on"], a["booth"],
                {1: "Must buy", 2: "Like", 3: "Maybe"}.get(a["interest"], ""),
                a["notes"], _links(conn, a["id"])]
        items = conn.execute(
            "SELECT * FROM wishlist_items WHERE artist_id=? ORDER BY priority, id",
            (a["id"],)).fetchall()
        if not items:
            rows.append(base + ["", "", "", "", "", "", ""])
        for it in items:
            rows.append(base + [
                it["title"], it["url"],
                f"{it['price']:.2f}" if it["price"] is not None else "",
                it["status"],
                {1: "Grail", 2: "Want", 3: "Someday"}.get(it["priority"], ""),
                it["target_con"], it["notes"]])
    return _write(headers, rows)


def artists_csv(conn):
    headers = ["Artist", "Shop", "Handle", "Tags", "Met at", "Met on", "Booth",
               "Interest", "Notes", "Links", "Open wants", "Open total"]
    rows = []
    for a in conn.execute("SELECT * FROM artists ORDER BY name COLLATE NOCASE"):
        agg = conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(price),0) s FROM wishlist_items "
            "WHERE artist_id=? AND status='want'", (a["id"],)).fetchone()
        rows.append([a["name"], a["shop_name"], ("@" + a["handle"]) if a["handle"] else "",
                     _tags(conn, a["id"]), a["met_at"], a["met_on"], a["booth"],
                     {1: "Must buy", 2: "Like", 3: "Maybe"}.get(a["interest"], ""),
                     a["notes"], _links(conn, a["id"]),
                     agg["n"], f"{agg['s']:.2f}"])
    return _write(headers, rows)


def wishlist_csv(conn, status="want"):
    headers = ["Priority", "Artist", "Item", "Price", "Link", "Status",
               "Target con", "Notes"]
    where, params = "", []
    if status and status != "all":
        where, params = "WHERE i.status=?", [status]
    rows = []
    for r in conn.execute(
        f"SELECT i.*, a.name AS artist FROM wishlist_items i "
        f"JOIN artists a ON a.id=i.artist_id {where} "
        f"ORDER BY i.priority, a.name COLLATE NOCASE, i.title", params):
        rows.append([
            {1: "Grail", 2: "Want", 3: "Someday"}.get(r["priority"], ""),
            r["artist"], r["title"],
            f"{r['price']:.2f}" if r["price"] is not None else "",
            r["url"], r["status"], r["target_con"], r["notes"]])
    return _write(headers, rows)


def mywishlist_csv(conn):
    """Minimal name/url/price/notes shape that generic wishlist sites import."""
    headers = ["Name", "URL", "Price", "Quantity", "Notes"]
    rows = []
    for r in conn.execute(
        "SELECT i.*, a.name AS artist FROM wishlist_items i "
        "JOIN artists a ON a.id=i.artist_id WHERE i.status='want' "
        "ORDER BY i.priority, a.name COLLATE NOCASE"):
        note_bits = [b for b in (r["notes"], r["target_con"]) if b]
        rows.append([
            f"{r['title']} - {r['artist']}",
            r["url"],
            f"{r['price']:.2f}" if r["price"] is not None else "",
            1,
            " | ".join(note_bits)])
    return _write(headers, rows)
