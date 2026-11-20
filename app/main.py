"""CardCatalog -- a library for the business cards you collect at conventions.

Single-user by design: run it on your own box, reach it over Tailscale, and hand
out one read-only share link when someone asks what's on your wish list.
"""
import os
import secrets
import time

from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import (HTMLResponse, RedirectResponse, JSONResponse,
                               PlainTextResponse, FileResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, exporter, importer, images, ocr
from .db import (INTEREST_LABELS, PRIORITY_LABELS, STATUS_LABELS, STATUSES,
                 UPLOAD_DIR)

HERE = os.path.dirname(os.path.abspath(__file__))
IMPORT_STAGING = os.path.join(db.DATA_DIR, "import-staging")

app = FastAPI(title="CardCatalog", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))


@app.on_event("startup")
def _startup():
    db.init_db()
    os.makedirs(IMPORT_STAGING, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    _sweep_staging()


app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


# ---------------------------------------------------------------- helpers

def _sweep_staging():
    """Drop staged CSVs older than an hour -- an abandoned import shouldn't linger."""
    cutoff = time.time() - 3600
    if not os.path.isdir(IMPORT_STAGING):
        return
    for fn in os.listdir(IMPORT_STAGING):
        path = os.path.join(IMPORT_STAGING, fn)
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass


def _ctx(request, **extra):
    base = {
        "request": request,
        "interest_labels": INTEREST_LABELS,
        "priority_labels": PRIORITY_LABELS,
        "status_labels": STATUS_LABELS,
        "statuses": STATUSES,
        "thumb": images.thumb_name,
    }
    base.update(extra)
    return base


def _artist_rows(conn, q="", tag="", interest="", sort="name"):
    sql = ["SELECT a.* FROM artists a"]
    params = []
    where = []
    if tag:
        sql.append("JOIN artist_tags at ON at.artist_id = a.id "
                   "JOIN tags t ON t.id = at.tag_id")
        where.append("t.name = ?")
        params.append(tag.lower())
    if q:
        where.append("(a.name LIKE ? OR a.shop_name LIKE ? OR a.handle LIKE ? "
                     "OR a.notes LIKE ? OR a.met_at LIKE ?)")
        params += [f"%{q}%"] * 5
    if interest:
        where.append("a.interest = ?")
        params.append(int(interest))
    if where:
        sql.append("WHERE " + " AND ".join(where))
    order = {
        "name": "a.name COLLATE NOCASE",
        "interest": "a.interest, a.name COLLATE NOCASE",
        "recent": "a.created_at DESC, a.id DESC",
        "con": "a.met_at COLLATE NOCASE, a.name COLLATE NOCASE",
    }.get(sort, "a.name COLLATE NOCASE")
    sql.append("GROUP BY a.id ORDER BY " + order)

    rows = []
    for a in conn.execute(" ".join(sql), params).fetchall():
        agg = conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(price), 0) s FROM wishlist_items "
            "WHERE artist_id=? AND status='want'", (a["id"],)).fetchone()
        rows.append({
            "a": a,
            "tags": db.artist_tags(conn, a["id"]),
            "links": db.artist_links(conn, a["id"]),
            "want_count": agg["n"],
            "want_total": agg["s"],
        })
    return rows


def _form_links(form):
    labels = form.getlist("link_label")
    urls = form.getlist("link_url")
    return list(zip(labels + [""] * len(urls), urls))[:len(urls)]


def _int_or(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _price_or_none(value):
    value = (value or "").strip().replace("$", "").replace(",", "")
    if not value:
        return None
    try:
        return round(float(value), 2)
    except ValueError:
        return None


# ---------------------------------------------------------------- library

@app.get("/", response_class=HTMLResponse)
def index(request: Request, q: str = "", tag: str = "", interest: str = "",
          sort: str = "name", view: str = "grid"):
    with db.db() as conn:
        rows = _artist_rows(conn, q, tag, interest, sort)
        totals = conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(price),0) s FROM wishlist_items "
            "WHERE status='want'").fetchone()
        return templates.TemplateResponse(request, "index.html", _ctx(
            request, rows=rows, tags=db.all_tags(conn), q=q, tag=tag,
            interest=interest, sort=sort, view=view,
            artist_count=conn.execute("SELECT COUNT(*) c FROM artists").fetchone()["c"],
            want_count=totals["n"], want_total=totals["s"],
        ))


@app.get("/artists/new", response_class=HTMLResponse)
def artist_new(request: Request):
    with db.db() as conn:
        return templates.TemplateResponse(request, "artist_form.html", _ctx(
            request, artist=None, tags=[], links=[], all_tags=db.all_tags(conn)))


@app.get("/artists/{artist_id}", response_class=HTMLResponse)
def artist_detail(request: Request, artist_id: int):
    with db.db() as conn:
        a = conn.execute("SELECT * FROM artists WHERE id=?", (artist_id,)).fetchone()
        if not a:
            raise HTTPException(404, "No such artist")
        items = conn.execute(
            "SELECT * FROM wishlist_items WHERE artist_id=? "
            "ORDER BY CASE status WHEN 'want' THEN 0 ELSE 1 END, priority, id",
            (artist_id,)).fetchall()
        open_total = sum(i["price"] or 0 for i in items if i["status"] == "want")
        return templates.TemplateResponse(request, "artist.html", _ctx(
            request, a=a, tags=db.artist_tags(conn, artist_id),
            links=db.artist_links(conn, artist_id), items=items,
            open_total=open_total))


@app.get("/artists/{artist_id}/edit", response_class=HTMLResponse)
def artist_edit(request: Request, artist_id: int):
    with db.db() as conn:
        a = conn.execute("SELECT * FROM artists WHERE id=?", (artist_id,)).fetchone()
        if not a:
            raise HTTPException(404, "No such artist")
        return templates.TemplateResponse(request, "artist_form.html", _ctx(
            request, artist=a, tags=db.artist_tags(conn, artist_id),
            links=db.artist_links(conn, artist_id), all_tags=db.all_tags(conn)))


@app.post("/artists")
async def artist_create(request: Request):
    form = await request.form()
    name = (form.get("name") or "").strip()
    if not name:
        return RedirectResponse("/artists/new?error=name", status_code=303)

    front = form.get("card_front")
    back = form.get("card_back")
    front_name = images.save_card_image(await front.read()) if hasattr(front, "read") else ""
    back_name = images.save_card_image(await back.read()) if hasattr(back, "read") else ""

    with db.db() as conn:
        cur = conn.execute(
            "INSERT INTO artists (name, shop_name, handle, met_at, met_on, booth, "
            "interest, notes, card_front, card_back, ocr_text) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (name, (form.get("shop_name") or "").strip(),
             (form.get("handle") or "").strip().lstrip("@"),
             (form.get("met_at") or "").strip(), (form.get("met_on") or "").strip(),
             (form.get("booth") or "").strip(), _int_or(form.get("interest"), 2),
             (form.get("notes") or "").strip(), front_name, back_name,
             (form.get("ocr_text") or "").strip()))
        artist_id = cur.lastrowid
        db.set_artist_tags(conn, artist_id, importer._split_tags(form.get("tags") or ""))
        db.set_artist_links(conn, artist_id, _form_links(form))
    return RedirectResponse(f"/artists/{artist_id}", status_code=303)


@app.post("/artists/{artist_id}")
async def artist_update(request: Request, artist_id: int):
    form = await request.form()
    name = (form.get("name") or "").strip()
    if not name:
        return RedirectResponse(f"/artists/{artist_id}/edit?error=name", status_code=303)

    with db.db() as conn:
        a = conn.execute("SELECT * FROM artists WHERE id=?", (artist_id,)).fetchone()
        if not a:
            raise HTTPException(404, "No such artist")

        front_name, back_name = a["card_front"], a["card_back"]
        for field, current in (("card_front", front_name), ("card_back", back_name)):
            upload = form.get(field)
            if hasattr(upload, "read"):
                saved = images.save_card_image(await upload.read())
                if saved:
                    images.delete_card_image(current)
                    if field == "card_front":
                        front_name = saved
                    else:
                        back_name = saved
            if form.get(f"remove_{field}"):
                images.delete_card_image(current)
                if field == "card_front":
                    front_name = ""
                else:
                    back_name = ""

        conn.execute(
            "UPDATE artists SET name=?, shop_name=?, handle=?, met_at=?, met_on=?, "
            "booth=?, interest=?, notes=?, card_front=?, card_back=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (name, (form.get("shop_name") or "").strip(),
             (form.get("handle") or "").strip().lstrip("@"),
             (form.get("met_at") or "").strip(), (form.get("met_on") or "").strip(),
             (form.get("booth") or "").strip(), _int_or(form.get("interest"), 2),
             (form.get("notes") or "").strip(), front_name, back_name, artist_id))
        db.set_artist_tags(conn, artist_id, importer._split_tags(form.get("tags") or ""))
        db.set_artist_links(conn, artist_id, _form_links(form))
    return RedirectResponse(f"/artists/{artist_id}", status_code=303)


@app.post("/artists/{artist_id}/delete")
def artist_delete(artist_id: int):
    with db.db() as conn:
        a = conn.execute("SELECT * FROM artists WHERE id=?", (artist_id,)).fetchone()
        if a:
            images.delete_card_image(a["card_front"])
            images.delete_card_image(a["card_back"])
            conn.execute("DELETE FROM artists WHERE id=?", (artist_id,))
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------- wishlist

@app.get("/wishlist", response_class=HTMLResponse)
def wishlist(request: Request, status: str = "want", sort: str = "priority",
             con: str = "", budget: str = ""):
    with db.db() as conn:
        where, params = [], []
        if status and status != "all":
            where.append("i.status = ?")
            params.append(status)
        if con:
            where.append("i.target_con = ?")
            params.append(con)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        order = {
            "priority": "i.priority, a.name COLLATE NOCASE",
            "price_desc": "i.price IS NULL, i.price DESC",
            "price_asc": "i.price IS NULL, i.price ASC",
            "artist": "a.name COLLATE NOCASE, i.priority",
        }.get(sort, "i.priority, a.name COLLATE NOCASE")

        items = conn.execute(
            f"SELECT i.*, a.name AS artist, a.card_front, a.handle "
            f"FROM wishlist_items i JOIN artists a ON a.id = i.artist_id "
            f"{clause} ORDER BY {order}", params).fetchall()
        total = sum(i["price"] or 0 for i in items)
        unpriced = sum(1 for i in items if i["price"] is None)
        cons = [r["target_con"] for r in conn.execute(
            "SELECT DISTINCT target_con FROM wishlist_items "
            "WHERE target_con <> '' ORDER BY target_con")]
        return templates.TemplateResponse(request, "wishlist.html", _ctx(
            request, items=items, total=total, unpriced=unpriced, status=status,
            sort=sort, con=con, cons=cons, budget=_price_or_none(budget),
            share_token=db.get_setting(conn, "share_token")))


@app.post("/artists/{artist_id}/items")
async def item_create(request: Request, artist_id: int):
    form = await request.form()
    title = (form.get("title") or "").strip()
    if not title:
        return RedirectResponse(f"/artists/{artist_id}?error=title", status_code=303)
    with db.db() as conn:
        conn.execute(
            "INSERT INTO wishlist_items (artist_id, title, url, price, priority, "
            "status, target_con, notes) VALUES (?,?,?,?,?,?,?,?)",
            (artist_id, title, (form.get("url") or "").strip(),
             _price_or_none(form.get("price")), _int_or(form.get("priority"), 2),
             (form.get("status") or "want"), (form.get("target_con") or "").strip(),
             (form.get("notes") or "").strip()))
    return RedirectResponse(f"/artists/{artist_id}", status_code=303)


@app.post("/items/{item_id}")
async def item_update(request: Request, item_id: int):
    form = await request.form()
    back = form.get("back") or "/wishlist"
    with db.db() as conn:
        row = conn.execute("SELECT artist_id FROM wishlist_items WHERE id=?",
                           (item_id,)).fetchone()
        if not row:
            raise HTTPException(404, "No such item")
        conn.execute(
            "UPDATE wishlist_items SET title=?, url=?, price=?, priority=?, status=?, "
            "target_con=?, notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            ((form.get("title") or "").strip(), (form.get("url") or "").strip(),
             _price_or_none(form.get("price")), _int_or(form.get("priority"), 2),
             (form.get("status") or "want"), (form.get("target_con") or "").strip(),
             (form.get("notes") or "").strip(), item_id))
    return RedirectResponse(back, status_code=303)


@app.post("/items/{item_id}/status")
async def item_status(request: Request, item_id: int):
    form = await request.form()
    status = form.get("status") or "want"
    if status not in STATUSES:
        status = "want"
    back = form.get("back") or "/wishlist"
    with db.db() as conn:
        conn.execute("UPDATE wishlist_items SET status=?, "
                     "updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, item_id))
    return RedirectResponse(back, status_code=303)


@app.post("/items/{item_id}/delete")
async def item_delete(request: Request, item_id: int):
    form = await request.form()
    back = form.get("back") or "/wishlist"
    with db.db() as conn:
        conn.execute("DELETE FROM wishlist_items WHERE id=?", (item_id,))
    return RedirectResponse(back, status_code=303)


# ---------------------------------------------------------------- tags

@app.get("/tags", response_class=HTMLResponse)
def tags_page(request: Request):
    with db.db() as conn:
        return templates.TemplateResponse(request, "tags.html", _ctx(
            request, tags=db.all_tags(conn)))


@app.post("/tags/{tag_id}/rename")
async def tag_rename(request: Request, tag_id: int):
    form = await request.form()
    new = (form.get("name") or "").strip().lower()
    with db.db() as conn:
        if new:
            existing = conn.execute("SELECT id FROM tags WHERE name=? AND id<>?",
                                    (new, tag_id)).fetchone()
            if existing:
                # Merge into the tag that already owns this name.
                conn.execute(
                    "UPDATE OR IGNORE artist_tags SET tag_id=? WHERE tag_id=?",
                    (existing["id"], tag_id))
                conn.execute("DELETE FROM artist_tags WHERE tag_id=?", (tag_id,))
                conn.execute("DELETE FROM tags WHERE id=?", (tag_id,))
            else:
                conn.execute("UPDATE tags SET name=? WHERE id=?", (new, tag_id))
    return RedirectResponse("/tags", status_code=303)


@app.post("/tags/{tag_id}/delete")
def tag_delete(tag_id: int):
    with db.db() as conn:
        conn.execute("DELETE FROM tags WHERE id=?", (tag_id,))
    return RedirectResponse("/tags", status_code=303)


# ---------------------------------------------------------------- OCR

@app.post("/ocr")
async def ocr_endpoint(card: UploadFile = File(...)):
    raw = await card.read()
    if not raw:
        return JSONResponse({"error": "empty upload"}, status_code=400)
    if len(raw) > 25 * 1024 * 1024:
        return JSONResponse({"error": "image too large (25MB max)"}, status_code=413)
    return JSONResponse(ocr.read_card(raw))


# ---------------------------------------------------------------- import

@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    return templates.TemplateResponse(request, "import.html", _ctx(
        request, stage="upload", fields=importer.TARGET_FIELDS,
        field_labels=importer.FIELD_LABELS))


@app.post("/import/preview", response_class=HTMLResponse)
async def import_preview(request: Request, csv_file: UploadFile = File(...)):
    raw = await csv_file.read()
    if not raw:
        return RedirectResponse("/import?error=empty", status_code=303)
    headers, rows, mapping = importer.sniff(raw)
    if not headers:
        return RedirectResponse("/import?error=parse", status_code=303)

    _sweep_staging()
    token = secrets.token_urlsafe(10)
    with open(os.path.join(IMPORT_STAGING, f"{token}.csv"), "wb") as fh:
        fh.write(raw)

    with db.db() as conn:
        summary = importer.do_import(conn, headers, rows, mapping, dry_run=True)

    return templates.TemplateResponse(request, "import.html", _ctx(
        request, stage="map", token=token, headers=headers,
        rows=rows[:12], row_count=len(rows), mapping=mapping,
        fields=importer.TARGET_FIELDS, field_labels=importer.FIELD_LABELS,
        summary=summary, filename=csv_file.filename))


@app.post("/import/commit", response_class=HTMLResponse)
async def import_commit(request: Request):
    form = await request.form()
    token = (form.get("token") or "").strip()
    # Token is generated server-side; refuse anything that isn't that shape.
    if not token or not token.replace("-", "").replace("_", "").isalnum():
        return RedirectResponse("/import?error=token", status_code=303)
    path = os.path.join(IMPORT_STAGING, f"{token}.csv")
    if not os.path.exists(path):
        return RedirectResponse("/import?error=expired", status_code=303)

    with open(path, "rb") as fh:
        raw = fh.read()
    headers, rows, _guess = importer.sniff(raw)
    mapping = {}
    for key, value in form.items():
        if key.startswith("col_") and value:
            mapping[key[4:]] = value

    with db.db() as conn:
        summary = importer.do_import(conn, headers, rows, mapping)
    os.remove(path)

    return templates.TemplateResponse(request, "import.html", _ctx(
        request, stage="done", summary=summary, row_count=len(rows)))


# ---------------------------------------------------------------- export

@app.get("/export/{which}.csv")
def export(which: str, status: str = "want"):
    makers = {
        "sheet": lambda c: exporter.sheet_csv(c),
        "artists": lambda c: exporter.artists_csv(c),
        "wishlist": lambda c: exporter.wishlist_csv(c, status),
        "mywishlist": lambda c: exporter.mywishlist_csv(c),
    }
    if which not in makers:
        raise HTTPException(404, "Unknown export")
    with db.db() as conn:
        body = makers[which](conn)
    return PlainTextResponse(body, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="cardcatalog-{which}.csv"'})


@app.get("/export", response_class=HTMLResponse)
def export_page(request: Request):
    with db.db() as conn:
        return templates.TemplateResponse(request, "export.html", _ctx(
            request, share_token=db.get_setting(conn, "share_token")))


# ---------------------------------------------------------------- sharing

@app.post("/share/rotate")
def share_rotate():
    with db.db() as conn:
        db.set_setting(conn, "share_token", secrets.token_urlsafe(12))
    return RedirectResponse("/export", status_code=303)


@app.get("/share/{token}", response_class=HTMLResponse)
def share_view(request: Request, token: str):
    with db.db() as conn:
        if not secrets.compare_digest(token, db.get_setting(conn, "share_token", "x")):
            raise HTTPException(404, "Not found")
        rows = conn.execute(
            "SELECT i.*, a.name AS artist, a.id AS aid, a.handle, a.card_front "
            "FROM wishlist_items i JOIN artists a ON a.id = i.artist_id "
            "WHERE i.status='want' "
            "ORDER BY i.priority, a.name COLLATE NOCASE, i.title").fetchall()
        grouped = {}
        for r in rows:
            grouped.setdefault((r["aid"], r["artist"], r["handle"]), []).append(r)
        artist_links = {
            aid: db.artist_links(conn, aid) for (aid, _n, _h) in grouped
        }
        return templates.TemplateResponse(request, "share.html", _ctx(
            request, grouped=grouped, artist_links=artist_links,
            total=sum(r["price"] or 0 for r in rows), count=len(rows)))


# ---------------------------------------------------------------- uploads

@app.get("/uploads/{filename}")
def upload(filename: str):
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(404, "Not found")
    path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000"})


@app.get("/healthz")
def healthz():
    return {"ok": True, "ocr": ocr.OCR_AVAILABLE}
