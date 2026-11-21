# CardCatalog

A library for the business cards you pick up at anime and art conventions.

You come home with fifty cards. A spreadsheet flattens them into fifty rows, but
what you actually have is two different things: **artists** (people, with tags,
links and a card you'd recognise on sight) and **wishlist items** (specific
pieces, zero to many per artist). CardCatalog keeps those separate, shows the
artists as a grid of their own cards, and still exports to CSV whenever you want
your spreadsheet back.

Runs on your own machine. Nothing leaves it.

## What it does

- **Card grid.** The photo of the card is the cover art, so you recognise a booth
  the way you actually remember it.
- **Both sides, auto-cropped.** Drop a photo of the front and the back. Each one
  has the card located in the frame, straightened out of whatever angle you shot
  it at, and cropped away from the tabletop — no manual cropping. If no
  card-shaped outline is found, the photo is kept whole rather than guessed at,
  and you can switch auto-crop off entirely.
- **OCR assist across both sides.** The front usually carries the name, the back
  the links and email, so the two readings are merged into one suggestion: name
  from the front, links unioned from both, tags from either. Straightening the
  card first measurably improves it — a test photo read as `Mariso) Vega` whole
  and `Marisol Vega` cropped. Runs locally — see *Privacy* below.
- **Tags.** Free-form and multi-select: `prints`, `acrylic charms`, `jjk`,
  `commissions open`, whatever you like. Rename one and it updates everywhere.
- **Per-artist wish lists.** One artist can have one item or fifteen, each with
  its own link, price, priority and status (`want` / `bought` / `sold out` /
  `passed`).
- **Budget check.** Set a number and see what your list costs against it before
  the con, with the low-priority items sorted to the bottom so you know what to cut.
- **A share link.** One read-only URL showing your open wants grouped by artist.
- **CSV in and out.** Import your existing sheet with a column mapper; export in
  four shapes, including one that round-trips back into CardCatalog.

## Quick start

```bash
docker compose up -d --build
```

Then open <http://localhost:8000>.

Everything persists in `./data` — `cardcatalog.db` plus the card images in
`uploads/`. Copy that one folder and you have the whole library backed up.

The image is around 450MB built, most of it OpenCV and Tesseract. That is the
cost of doing card detection and text recognition on your own hardware instead
of sending photos to a service.

### Reaching it over Tailscale

`docker-compose.yml` binds to `127.0.0.1:8000`, so it is not exposed to your LAN.
From another device on your tailnet, use the host's Tailscale address:

```bash
http://<your-machine>.<your-tailnet>.ts.net:8000
```

If your Tailscale runs on the host (not in the container), that works as-is. To
reach it from outside your tailnet — handing the share link to a friend who
isn't on it — put it behind a Tailscale Funnel, or just send them a CSV export.

### Running without Docker

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo apt install tesseract-ocr tesseract-ocr-eng   # the OCR engine
./run-dev.sh
```

## Privacy — all processing is local

No part of this sends your cards, your artist list, or anything else to a remote
service. Specifically:

- **No AI service is involved.** OCR is [Tesseract](https://tesseract-ocr.github.io/),
  an open-source engine that runs as a local binary inside your container. There
  is no model API, no inference endpoint, no account, no telemetry.
- **No AI in the auto-crop either.** Card detection is classical computer
  vision in OpenCV — edge detection and contour fitting. No model, no inference,
  no upload. The OpenCV build links no network or TLS libraries at all.
- **No HTTP client in the codebase.** The app imports `fastapi`, `pillow`,
  `opencv-python-headless`, `numpy`, `pytesseract`, and the Python standard
  library. Nothing that can make an outbound request.
- **No CDN.** All CSS and JavaScript is served from the container. No Google
  Fonts, no script tags pointing at someone else's server, no analytics. The app
  works with the machine fully offline.
- **Images never leave the box.** A card photo goes from your browser to your
  server, gets resized by Pillow and read by Tesseract, and is written to
  `./data/uploads`. That is the whole journey.

You can verify this yourself — the check runs the real pipeline, auto-crop and
OCR both, inside a network namespace with no interfaces at all, so it would fail
if anything tried to phone home:

```bash
sudo ./tools/check_offline.sh path/to/a-card-photo.jpg
```

Artists' work stays between you and your own disk.

## Importing your existing sheet

1. In Google Sheets: **File → Download → Comma-separated values**.
2. **Import** in the nav, choose the file.
3. Check the guessed column mapping and fix anything wrong.
4. Confirm.

Column headers are matched by name, so `Artist`, `Shop`, `Instagram`,
`Convention`, `Booth`, `Tags`, `Price`, `Status` and friends are usually picked
up without help. A dry run tells you exactly what will be created before
anything is written.

Things the importer handles:

- **Repeated artists collapse.** Three rows for the same artist become one
  artist with three wishlist items.
- **Re-importing is safe.** Artists are matched by name and added to rather than
  duplicated; an item the artist already has is left alone.
- **Messy values.** `$25.00` and `25` both parse. `bought`, `purchased`, `have`,
  `yes` all mean bought. Tags split on commas, semicolons, slashes and pipes.
- **Interest levels.** `High`, `***`, `5`, `must buy` all land sensibly.

## Exports

| File | Shape | For |
|---|---|---|
| `sheet.csv` | one row per item, artist columns repeated | Google Sheets, and a full backup that re-imports cleanly |
| `artists.csv` | one row per artist | a quick roster |
| `wishlist.csv` | open wants, priority first | pasting into a shared sheet |
| `mywishlist.csv` | name / URL / price / qty / notes | generic wishlist sites |

## Look and feel

The theme is a reading room: walnut shelves in the dark theme, parchment and
pale oak in the light one, with a shaft of afternoon sun across the top of the
page and accents borrowed from what grows outside — **pine** for actions,
**bluebell** for tags, **new leaf**, **honey**, **rosehip** and **open sky** for
status.

Nothing is a flat fill. Every surface is a gradient between a lit top stop
(`-hi`) and a shaded bottom one (`-lo`), and light comes from above
consistently, so depth means something:

- **Raised** (`--lift-1/2/3`) — cards, buttons, chips, panels, stat tiles. A lit
  top edge, a dark bottom edge, and a cast shadow that grows on hover.
- **Recessed** (`--sink`, `--sink-deep`) — inputs, the budget trough, table
  headers, the OCR dropzone, and the frame a card photo sits in, like a print
  behind a mat. Buttons swap to recessed while pressed.

Wood grain is a faint repeating gradient on the shelf rail; the card photo gets
a diagonal sheen like glass catching the light.

## Colour and accessibility

35 OKLCH tokens per theme. Because surfaces are gradients, text sits on a
*range* of colours rather than one, so each surface contributes three samples —
its base, its `-hi` stop and its `-lo` stop — and every foreground is solved
against the worst of all twelve. Both themes are selected independently; dark is
not an inverted light.

| | requirement | light | dark |
|---|---|---|---|
| `--text` | AAA body, ≥ 7:1 | 11.49:1 | 8.93:1 |
| `--text-muted` | AA, ≥ 4.5:1 | 4.51:1 | 4.51:1 |
| `--border` | AA non-text, ≥ 3:1 | 3.01:1 | 3.00:1 |
| accents as text | AA, ≥ 4.5:1 | 4.60:1 | 5.00:1 |
| `--on-accent` across a fill | AA, ≥ 4.5:1 | 5.29:1 | 8.22:1 |

Those are worst-case numbers across every gradient stop, not midpoints. Re-run
the whole matrix after changing any colour — it reads the tokens straight out of
the stylesheet, so it catches drift:

```bash
python3 tools/check_contrast.py
```

Text itself stays a flat colour: gradient text can't be contrast-checked and
reads poorly at body sizes.

Colour never carries meaning on its own. `--danger` and `--success` are not
separable under deuteranopia, so every status chip pairs its colour with a glyph
*and* a word, and every priority bead sits beside its label. Depth is decorative
only — nothing is distinguished by shadow alone. `prefers-reduced-motion`
disables the hover lifts.

## Layout

```
app/
  main.py        routes
  db.py          SQLite schema and helpers -- the whole data model
  ocr.py         Tesseract pipeline, card-text parser, front/back merging
  autocrop.py    finds the card in a photo and straightens it (OpenCV)
  importer.py    CSV column guessing and merge-on-import
  exporter.py    the four CSV shapes
  images.py      upload handling, resizing, thumbnails
  templates/     Jinja2
  static/        one stylesheet, one script, no dependencies
tools/
  check_contrast.py   WCAG verification, reads style.css
  check_offline.sh    proves OCR needs no network
data/            your library (gitignored) -- db + uploads
```

Single user by design. There are no accounts, and anyone who can reach the port
can edit the library, which is the right trade for something sitting on a
tailnet. Don't put it on the open internet without a proxy in front.
