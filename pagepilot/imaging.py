"""Image clean-up used before OCR: orientation, skew, lighting, scale, table-line detection."""
import cv2
import numpy as np
from PIL import Image, ImageOps


# ----------------------------------------------------------------------------- loading
def pil_to_gray(img: Image.Image) -> np.ndarray:
    """Any PIL image -> upright 8-bit grayscale numpy array (transparency becomes white)."""
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    return np.array(img.convert("L"))


def limit_size(gray: np.ndarray, max_side: int) -> np.ndarray:
    h, w = gray.shape
    longest = max(h, w)
    if longest <= max_side:
        return gray
    f = max_side / float(longest)
    return cv2.resize(gray, (max(1, int(w * f)), max(1, int(h * f))), interpolation=cv2.INTER_AREA)


# ----------------------------------------------------------------------------- polarity / lighting
def ensure_dark_on_light(gray: np.ndarray) -> np.ndarray:
    """Dark-mode screenshots (light text on dark background) are inverted."""
    if float(np.median(gray)) < 100:
        return 255 - gray
    return gray


def flatten_background(gray: np.ndarray) -> np.ndarray:
    """Even out shadows / uneven lighting (phone photos). Clean scans are returned untouched."""
    h, w = gray.shape
    f = 0.25 if max(h, w) > 1600 else 1.0
    small = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f != 1.0 else gray
    dil = cv2.dilate(small, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
    bg = cv2.medianBlur(dil, 21)
    lo, hi = np.percentile(bg, [5, 95])
    if hi - lo < 30 and lo > 150:          # already an even, light page: leave it alone
        return gray
    if f != 1.0:
        bg = cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR)
    bg = np.maximum(bg, 1)
    return cv2.divide(gray, bg, scale=255)


# ----------------------------------------------------------------------------- rotation
def rotate_keep(gray: np.ndarray, angle: float, border: int = 255) -> np.ndarray:
    """Rotate by `angle` degrees (counter-clockwise positive), enlarging the canvas."""
    h, w = gray.shape
    c = (w / 2.0, h / 2.0)
    M = cv2.getRotationMatrix2D(c, angle, 1.0)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    M[0, 2] += nw / 2.0 - c[0]
    M[1, 2] += nh / 2.0 - c[1]
    return cv2.warpAffine(gray, M, (nw, nh), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=border)


def estimate_skew(gray: np.ndarray, max_angle: float = 10.0) -> float:
    """Angle (degrees, same convention as rotate_keep) that makes text lines horizontal."""
    h, w = gray.shape
    scale = 1000.0 / max(h, w) if max(h, w) > 1000 else 1.0
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale != 1.0 else gray
    _, bw = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    m = int(0.02 * min(bw.shape))
    if m > 0:
        bw[:m, :] = 0
        bw[-m:, :] = 0
        bw[:, :m] = 0
        bw[:, -m:] = 0
    if cv2.countNonZero(bw) < 300 or cv2.countNonZero(bw) > 0.5 * bw.size:
        return 0.0
    hh, ww = bw.shape
    center = (ww / 2.0, hh / 2.0)

    def score(angle: float) -> float:
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        r = cv2.warpAffine(bw, M, (ww, hh), flags=cv2.INTER_NEAREST)
        prof = r.sum(axis=1, dtype=np.float64) / 255.0
        return float(np.sum(np.diff(prof) ** 2))

    base = score(0.0)
    coarse = np.arange(-max_angle, max_angle + 0.01, 1.0)
    best = max(coarse, key=score)
    fine = np.arange(best - 1.0, best + 1.01, 0.1)
    best = max(fine, key=score)
    if abs(best) < 0.25 or base <= 0 or score(best) / base < 1.03:
        return 0.0
    return float(best)


def deskew(gray: np.ndarray) -> np.ndarray:
    angle = estimate_skew(gray)
    if angle == 0.0:
        return gray
    return rotate_keep(gray, angle)


def rotate_by_osd(gray: np.ndarray, degrees_clockwise: int) -> np.ndarray:
    if degrees_clockwise == 90:
        return cv2.rotate(gray, cv2.ROTATE_90_CLOCKWISE)
    if degrees_clockwise == 180:
        return cv2.rotate(gray, cv2.ROTATE_180)
    if degrees_clockwise == 270:
        return cv2.rotate(gray, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return gray


# ----------------------------------------------------------------------------- scale
def scale_for_ocr(gray: np.ndarray, max_side: int) -> np.ndarray:
    """Tesseract wants roughly 300 DPI. Upscale small images, cap huge ones."""
    h, w = gray.shape
    short = min(h, w)
    f = 1.0
    if short < 1500:
        f = min(3.0, 1500.0 / short)
    if max(h, w) * f > max_side:
        f = max_side / float(max(h, w))
    if abs(f - 1.0) < 0.05:
        return gray
    interp = cv2.INTER_CUBIC if f > 1 else cv2.INTER_AREA
    return cv2.resize(gray, (max(1, int(w * f)), max(1, int(h * f))), interpolation=interp)


def resize_factor(gray: np.ndarray, f: float) -> np.ndarray:
    h, w = gray.shape
    return cv2.resize(gray, (max(1, int(w * f)), max(1, int(h * f))),
                      interpolation=cv2.INTER_CUBIC if f > 1 else cv2.INTER_AREA)


# ----------------------------------------------------------------------------- table grid detection
def _cluster_positions(values, tol: float):
    """Merge nearby 1-D positions (line centres) into single positions."""
    values = sorted(values)
    out, cur = [], []
    for v in values:
        if cur and v - cur[-1] > tol:
            out.append(sum(cur) / len(cur))
            cur = []
        cur.append(v)
    if cur:
        out.append(sum(cur) / len(cur))
    return out


def _drop_close(positions, min_gap: float):
    out = []
    for p in positions:
        if not out or p - out[-1] >= min_gap:
            out.append(p)
    return out


def find_grid_tables(gray: np.ndarray):
    """Detect ruled tables (visible grid lines).

    Returns (tables, erase_mask):
      tables     - list of {"xs": [...], "ys": [...]} in pixel coordinates (sorted line positions)
      erase_mask - uint8 mask of the grid-line pixels of accepted tables (to whiten before OCR)
    """
    h, w = gray.shape
    block = max(15, (min(h, w) // 60) | 1)
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block, 12)

    hk, vk = max(25, w // 45), max(25, h // 45)
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (hk, 1)))
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, vk)))
    mask = cv2.bitwise_or(horiz, vert)
    erase_mask = np.zeros_like(mask)
    if cv2.countNonZero(mask) == 0:
        return [], erase_mask

    joined = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)

    tables = []
    line_tol = max(4.0, min(h, w) * 0.004)
    for i in range(1, n):
        x, y, cw, ch, area = stats[i]
        if cw < 3 * hk or ch < 30:
            continue
        comp = (labels[y:y + ch, x:x + cw] == i).astype(np.uint8) * 255
        hc = cv2.bitwise_and(horiz[y:y + ch, x:x + cw], comp)
        vc = cv2.bitwise_and(vert[y:y + ch, x:x + cw], comp)

        ys, xs = [], []
        cnts, _ = cv2.findContours(hc, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            rx, ry, rw, rh = cv2.boundingRect(c)
            if rw >= 0.35 * cw:
                ys.append(y + ry + rh / 2.0)
        cnts, _ = cv2.findContours(vc, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            rx, ry, rw, rh = cv2.boundingRect(c)
            if rh >= 0.35 * ch:
                xs.append(x + rx + rw / 2.0)

        ys = _drop_close(_cluster_positions(ys, line_tol), 12)
        xs = _drop_close(_cluster_positions(xs, line_tol), 12)
        if len(ys) < 3 or len(xs) < 3 or len(ys) - 1 > 300 or len(xs) - 1 > 40:
            continue                      # need at least 2 rows x 2 columns
        tables.append({"xs": xs, "ys": ys})
        region = (slice(y, y + ch), slice(x, x + cw))
        erase_mask[region] = cv2.bitwise_or(erase_mask[region], cv2.bitwise_and(mask[region], comp))

    if tables:
        erase_mask = cv2.dilate(erase_mask, np.ones((3, 3), np.uint8), iterations=1)
    return tables, erase_mask
