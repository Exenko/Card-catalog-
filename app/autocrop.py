"""Find the business card in a photo, straighten it, and cut the rest away.

A phone photo of a card on a table is mostly table, usually at an angle. This
locates the card's four corners, corrects the perspective, and returns just the
card -- which makes the library grid look like a shelf of cards rather than a
shelf of tabletops, and measurably helps OCR.

Everything here fails safe: if the card can't be found with confidence, the
original image is returned untouched. A wrong crop is far worse than no crop.
"""
import cv2
import numpy as np

# A detection has to look like a card to be accepted.
MIN_AREA_FRAC = 0.045  # a card held well back from the lens is still small
MAX_AREA_FRAC = 0.92   # larger and the card already fills the frame; leave it
MIN_RATIO = 1.15       # long/short edge. ISO 7810 cards are 1.586, US 1.75,
MAX_RATIO = 2.60       # but artists use square-ish and tall cards too.
WORK_EDGE = 1000       # detect on a downscaled copy, crop the full-size one


def _order_corners(pts):
    """Return the four points as top-left, top-right, bottom-right, bottom-left."""
    pts = np.array(pts, dtype="float32").reshape(4, 2)
    out = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    out[0] = pts[np.argmin(s)]        # tl has the smallest x+y
    out[2] = pts[np.argmax(s)]        # br the largest
    d = np.diff(pts, axis=1)
    out[1] = pts[np.argmin(d)]        # tr has the smallest y-x
    out[3] = pts[np.argmax(d)]
    return out


def _quad_is_plausible(quad, frame_area):
    area = cv2.contourArea(quad.astype("float32"))
    if not (MIN_AREA_FRAC * frame_area <= area <= MAX_AREA_FRAC * frame_area):
        return False
    tl, tr, br, bl = quad
    widths = [np.linalg.norm(tr - tl), np.linalg.norm(br - bl)]
    heights = [np.linalg.norm(bl - tl), np.linalg.norm(br - tr)]
    w, h = max(widths), max(heights)
    if min(w, h) < 40:
        return False
    # Opposite edges should be roughly equal -- guards against grabbing a
    # shadow or a table edge that merely happens to be large.
    if min(widths) / max(widths) < 0.6 or min(heights) / max(heights) < 0.6:
        return False
    ratio = max(w, h) / min(w, h)
    return MIN_RATIO <= ratio <= MAX_RATIO


def _edge_maps(bgr, gray):
    """Several ways of seeing the card's outline.

    Luminance edges disappear when a pale card sits on a pale desk (or a dark
    one on a dark desk), so colour and local-contrast channels are tried too.
    Each map is cheap; the plausibility check decides which one was right.
    """
    maps = []
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # 1/2. Canny with image-derived thresholds, then a permissive pass.
    med = float(np.median(blurred))
    maps.append(cv2.Canny(blurred, int(max(0, 0.66 * med)),
                          int(min(255, 1.33 * med))))
    maps.append(cv2.Canny(blurred, 30, 90))

    # 3. Otsu: a card much lighter or darker than the desk.
    _t, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    maps.append(cv2.Canny(otsu, 50, 150))

    # 4. CLAHE lifts local contrast, which is what a same-tone desk destroys.
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
    maps.append(cv2.Canny(cv2.GaussianBlur(clahe, (5, 5), 0), 30, 90))

    # 5. Scharr gradient magnitude: finds soft edges Canny's thresholds miss.
    gx = cv2.Scharr(blurred, cv2.CV_32F, 1, 0)
    gy = cv2.Scharr(blurred, cv2.CV_32F, 0, 1)
    mag = cv2.magnitude(gx, gy)
    mag = cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    _t, grad = cv2.threshold(mag, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    maps.append(grad)

    # 6/7. Colour channels: a warm card on a cool desk differs in a/b even when
    # it matches in brightness.
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    for ch in (1, 2):
        c = cv2.GaussianBlur(lab[:, :, ch], (5, 5), 0)
        if float(c.std()) < 1.5:
            continue          # flat channel, nothing to find
        _t, binc = cv2.threshold(c, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        maps.append(cv2.Canny(binc, 50, 150))

    # 8. Saturation, for a colourful card on a neutral desk.
    sat = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[:, :, 1]
    if float(sat.std()) >= 1.5:
        _t, bins = cv2.threshold(cv2.GaussianBlur(sat, (5, 5), 0), 0, 255,
                                 cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        maps.append(cv2.Canny(bins, 50, 150))
    return maps


def _candidates(bgr, gray):
    """Yield plausible 4-point contours from every edge strategy."""
    kernel = np.ones((5, 5), np.uint8)
    for edges in _edge_maps(bgr, gray):
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
            peri = cv2.arcLength(c, True)
            if peri < 80:
                continue
            for eps in (0.02, 0.04, 0.06):
                approx = cv2.approxPolyDP(c, eps * peri, True)
                if len(approx) == 4 and cv2.isContourConvex(approx):
                    yield approx.reshape(4, 2).astype("float32")
                    break
            else:
                rect = cv2.minAreaRect(c)
                box = cv2.boxPoints(rect).astype("float32")
                if cv2.contourArea(box) > 0 and \
                        cv2.contourArea(c) > 0.80 * cv2.contourArea(box):
                    yield box


def find_card(bgr):
    """Return the card's 4 corners in full-resolution coords, or None."""
    h, w = bgr.shape[:2]
    scale = WORK_EDGE / max(h, w) if max(h, w) > WORK_EDGE else 1.0
    small = cv2.resize(bgr, None, fx=scale, fy=scale,
                       interpolation=cv2.INTER_AREA) if scale != 1.0 else bgr
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    frame_area = small.shape[0] * small.shape[1]

    best, best_area = None, 0.0
    for quad in _candidates(small, gray):
        ordered = _order_corners(quad)
        if not _quad_is_plausible(ordered, frame_area):
            continue
        area = cv2.contourArea(ordered)
        if area > best_area:
            best, best_area = ordered, area
    if best is None:
        return None
    return best / scale


def warp(bgr, quad):
    """Flatten the quadrilateral into an upright rectangle."""
    tl, tr, br, bl = quad
    width = int(round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))))
    height = int(round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))))
    width, height = max(width, 1), max(height, 1)
    dst = np.array([[0, 0], [width - 1, 0],
                    [width - 1, height - 1], [0, height - 1]], dtype="float32")
    m = cv2.getPerspectiveTransform(quad.astype("float32"), dst)
    out = cv2.warpPerspective(bgr, m, (width, height), flags=cv2.INTER_CUBIC)
    # A card photographed in portrait is still a landscape card.
    if height > width and height / max(width, 1) > 1.15:
        out = cv2.rotate(out, cv2.ROTATE_90_CLOCKWISE)
    return out


def autocrop(bgr):
    """(image, cropped?) -- the straightened card, or the original untouched."""
    try:
        quad = find_card(bgr)
    except cv2.error:
        return bgr, False
    if quad is None:
        return bgr, False
    try:
        return warp(bgr, quad), True
    except cv2.error:
        return bgr, False
