"""Business-card OCR: read a card photo, guess name / handle / links.

Cards are sparse, high-contrast, often rotated and small, so we upscale and run
Tesseract twice (block mode + sparse mode) and merge what comes back. Everything
here is a *suggestion* -- the UI pre-fills a form the user corrects.
"""
import io
import re
import unicodedata

from PIL import Image, ImageOps, ImageFilter

try:
    import pytesseract
    OCR_AVAILABLE = True
except Exception:  # pragma: no cover - pytesseract missing
    OCR_AVAILABLE = False

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]{2,}")
URL_RE = re.compile(r"(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)+(?:/[^\s,;]*)?", re.I)
HANDLE_RE = re.compile(r"(?<![\w.@])@([A-Za-z0-9._]{2,30})")
PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")

# Domain fragment -> human label. Order matters: first hit wins.
PLATFORMS = [
    ("instagram.com", "Instagram"), ("instagr.am", "Instagram"),
    ("bsky.app", "Bluesky"), ("bsky.social", "Bluesky"),
    ("twitter.com", "Twitter/X"), ("x.com", "Twitter/X"),
    ("ko-fi.com", "Ko-fi"), ("kofi.com", "Ko-fi"),
    ("patreon.com", "Patreon"), ("gumroad.com", "Gumroad"),
    ("etsy.com", "Etsy"), ("bigcartel.com", "Big Cartel"),
    ("shopify.com", "Shopify"), ("storenvy.com", "Storenvy"),
    ("inprnt.com", "INPRNT"), ("redbubble.com", "Redbubble"),
    ("threadless.com", "Threadless"), ("displate.com", "Displate"),
    ("tumblr.com", "Tumblr"), ("deviantart.com", "DeviantArt"),
    ("artstation.com", "ArtStation"), ("pixiv.net", "Pixiv"),
    ("carrd.co", "Carrd"), ("linktr.ee", "Linktree"), ("linktree.com", "Linktree"),
    ("beacons.ai", "Beacons"), ("throne.com", "Throne"), ("throne.me", "Throne"),
    ("vgen.co", "VGen"), ("youtube.com", "YouTube"), ("tiktok.com", "TikTok"),
    ("facebook.com", "Facebook"), ("twitch.tv", "Twitch"),
    ("discord.gg", "Discord"), ("discord.com", "Discord"),
]

# Things that look like a name but aren't.
NOISE_WORDS = {
    "illustrator", "artist", "illustration", "art", "prints", "stickers",
    "commissions", "commission", "open", "shop", "store", "designer",
    "freelance", "email", "contact", "instagram", "twitter", "bluesky",
    "thank", "thanks", "you", "follow", "me", "my", "online", "available",
    "charms", "keychains", "acrylic", "buttons", "pins", "zines", "etsy",
}

# Real TLDs we trust in bare (scheme-less) text. Keeps "Fig.1" out of the links.
GOOD_TLDS = {
    "com", "net", "org", "co", "io", "me", "shop", "store", "art", "gallery",
    "studio", "design", "ink", "us", "uk", "ca", "jp", "eu", "de", "fr", "tv",
    "gg", "ee", "ai", "app", "social", "xyz", "info", "biz", "cc", "online",
}


def _variants(img):
    """A few preprocessed versions of the card, cheapest first."""
    img = ImageOps.exif_transpose(img).convert("L")
    # Upscale small photos; Tesseract wants ~300dpi-ish glyph heights.
    w, h = img.size
    target = 1800
    if max(w, h) < target:
        scale = target / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    base = ImageOps.autocontrast(img, cutoff=2)
    yield base
    yield base.filter(ImageFilter.SHARPEN)
    # Hard threshold helps cards with textured or tinted backgrounds.
    yield base.point(lambda p: 255 if p > 140 else 0)


def extract_text(image_bytes):
    """Return the raw OCR text for a card image (best effort, '' on failure)."""
    if not OCR_AVAILABLE:
        return ""
    try:
        img = Image.open(io.BytesIO(image_bytes))
    except Exception:
        return ""

    chunks = []
    for variant in _variants(img):
        for psm in ("6", "11"):  # uniform block, then sparse text
            try:
                text = pytesseract.image_to_string(variant, config=f"--oem 1 --psm {psm}")
            except Exception:
                continue
            if text and text.strip():
                chunks.append(text)
        if sum(len(c) for c in chunks) > 160:
            break  # already plenty to work with
    return "\n".join(chunks)


def _clean_line(line):
    line = unicodedata.normalize("NFKC", line)
    line = re.sub(r"[|_~^`]+", " ", line)
    return re.sub(r"\s{2,}", " ", line).strip(" .,:;-•")


def _looks_like_name(line):
    if not (2 <= len(line) <= 42):
        return False
    if "@" in line or EMAIL_RE.search(line):
        return False
    if re.search(r"\d{3,}", line):
        return False
    words = [w for w in re.split(r"[\s/]+", line) if w]
    if not words or len(words) > 5:
        return False
    if any(w.strip(".,").lower() in NOISE_WORDS for w in words):
        return False
    letters = sum(c.isalpha() for c in line)
    if letters < max(2, len(line) * 0.6):
        return False
    # A bare domain is not a name.
    if _is_domain(line.replace(" ", "")):
        return False
    return True


def _is_domain(token):
    token = token.strip().rstrip("/.")
    if "." not in token or " " in token:
        return False
    tld = token.rsplit(".", 1)[-1].split("/")[0].lower()
    return tld in GOOD_TLDS


def _label_for(url):
    low = url.lower()
    for frag, label in PLATFORMS:
        if frag in low:
            return label
    host = re.sub(r"^https?://", "", low).split("/")[0]
    if host.startswith("www."):
        host = host[4:]
    return host.split(".")[0].title() if host else "Website"


def parse_card(text):
    """Turn OCR text into suggested field values."""
    lines = [_clean_line(l) for l in text.splitlines()]
    lines = [l for l in lines if l]

    emails, urls, handles, phones = [], [], [], []
    for line in lines:
        for m in EMAIL_RE.findall(line):
            if m.lower() not in (e.lower() for e in emails):
                emails.append(m)
        stripped = EMAIL_RE.sub(" ", line)
        for m in HANDLE_RE.findall(stripped):
            if m.lower() not in (h.lower() for h in handles):
                handles.append(m)
        for m in URL_RE.findall(stripped):
            tok = m.strip().rstrip(".,;)")
            if not _is_domain(tok):
                continue
            norm = tok if tok.lower().startswith("http") else "https://" + tok
            if norm.lower() not in (u.lower() for u in urls):
                urls.append(norm)
        for m in PHONE_RE.findall(stripped):
            digits = re.sub(r"\D", "", m)
            if 9 <= len(digits) <= 15:
                phones.append(m.strip())

    # Name: prefer an early line that reads like a name. Cards put it near the top.
    name = ""
    for line in lines[:8]:
        if _looks_like_name(line):
            name = line
            break
    if not name:
        # Fall back to the handle or the shop domain.
        if handles:
            name = handles[0]
        elif urls:
            name = _label_for(urls[0])

    handle = handles[0] if handles else ""
    if not handle and emails:
        handle = emails[0].split("@")[0]

    # Shop name: a distinct domain-ish or multi-word line that isn't the name.
    shop = ""
    for u in urls:
        if _label_for(u) not in {
            "Instagram", "Twitter/X", "Bluesky", "Tumblr", "TikTok",
            "YouTube", "Facebook", "Discord", "Twitch", "Pixiv",
        }:
            shop = _label_for(u)
            break

    links = [{"label": _label_for(u), "url": u} for u in urls[:10]]
    suggested_tags = _suggest_tags(text)

    return {
        "name": name,
        "handle": handle,
        "shop_name": shop,
        "email": emails[0] if emails else "",
        "emails": emails,
        "handles": handles,
        "phones": phones[:2],
        "links": links,
        "tags": suggested_tags,
        "raw_text": text.strip(),
    }


TAG_HINTS = {
    "prints": ["print", "prints", "poster", "posters", "giclee"],
    "stickers": ["sticker", "stickers", "decal"],
    "acrylic charms": ["charm", "charms", "acrylic", "keychain", "keychains"],
    "pins": ["pin", "pins", "enamel", "button", "buttons"],
    "apparel": ["shirt", "tshirt", "t-shirt", "hoodie", "apparel", "tee"],
    "zines": ["zine", "zines", "comic", "comics", "manga", "doujin"],
    "plush": ["plush", "plushie", "plushies"],
    "commissions open": ["commission", "commissions", "comms"],
    "stationery": ["washi", "notebook", "bookmark", "bookmarks", "postcard"],
}


def _suggest_tags(text):
    low = text.lower()
    found = []
    for tag, needles in TAG_HINTS.items():
        if any(re.search(rf"\b{re.escape(n)}\b", low) for n in needles):
            found.append(tag)
    return found


def read_card(image_bytes):
    """Full pipeline: bytes in, suggestions out."""
    text = extract_text(image_bytes)
    result = parse_card(text)
    result["ocr_available"] = OCR_AVAILABLE
    return result


def merge_sides(front, back):
    """Combine the readings from both sides of one card.

    The front of an art card usually carries the name; the back carries the
    links, the shop and the email. Either may be missing, so take the first
    confident value for the single-valued fields and union the rest.
    """
    sides = [s for s in (front, back) if s]
    if not sides:
        return None
    if len(sides) == 1:
        return dict(sides[0])

    merged = dict(sides[0])
    for field in ("name", "handle", "shop_name", "email"):
        for s in sides:
            if s.get(field):
                merged[field] = s[field]
                break
        else:
            merged[field] = ""

    # A name is a person; a bare handle on the back shouldn't beat the front's.
    if front and front.get("name"):
        merged["name"] = front["name"]

    seen, links = set(), []
    for s in sides:
        for link in s.get("links", []):
            key = link["url"].rstrip("/").lower()
            if key not in seen:
                seen.add(key)
                links.append(link)
    merged["links"] = links

    for field in ("tags", "emails", "handles", "phones"):
        out, seen_v = [], set()
        for s in sides:
            for v in s.get(field, []):
                if v.lower() not in seen_v:
                    seen_v.add(v.lower())
                    out.append(v)
        merged[field] = out

    merged["raw_text"] = "\n\n".join(
        f"--- {label} ---\n{s['raw_text']}"
        for label, s in (("front", front), ("back", back))
        if s and s.get("raw_text")).strip()
    return merged
