"""Thin, defensive wrapper around Tesseract."""
import re
from typing import List, Optional, Tuple

import numpy as np
import pytesseract
from pytesseract import Output

from . import imaging
from .config import Config
from .errors import ExtractError
from .models import Word

if Config.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = Config.TESSERACT_CMD

LANG_NAMES = {
    "eng": "English", "nep": "Nepali", "hin": "Hindi", "ben": "Bengali", "urd": "Urdu",
    "san": "Sanskrit", "mar": "Marathi", "tam": "Tamil", "tel": "Telugu", "guj": "Gujarati",
    "fra": "French", "deu": "German", "spa": "Spanish", "por": "Portuguese", "ita": "Italian",
    "rus": "Russian", "ara": "Arabic", "chi_sim": "Chinese (Simplified)", "chi_tra": "Chinese (Traditional)",
    "jpn": "Japanese", "kor": "Korean", "tha": "Thai", "vie": "Vietnamese", "tur": "Turkish",
}
_JUNK = re.compile(r"^[|_~`'\".,:;\-—–=]+$")

_installed: Optional[List[str]] = None


def installed_languages() -> List[str]:
    global _installed
    if _installed is None:
        try:
            langs = pytesseract.get_languages(config="")
        except Exception:
            langs = []
        _installed = sorted(l for l in langs if l not in ("osd", "equ", "snum") and not l.startswith("."))
    return _installed


def language_options() -> List[dict]:
    """Options for the language dropdown: each language alone, plus English + X combos."""
    langs = installed_languages()
    opts = []
    if "eng" in langs:
        opts.append({"code": "eng", "label": "English"})
    for l in langs:
        if l != "eng":
            opts.append({"code": l, "label": LANG_NAMES.get(l, l)})
            if "eng" in langs:
                opts.append({"code": f"eng+{l}", "label": f"English + {LANG_NAMES.get(l, l)}"})
    if not opts and langs:
        opts = [{"code": l, "label": LANG_NAMES.get(l, l)} for l in langs]
    return opts


def validate_lang(lang: str) -> str:
    lang = (lang or "eng").strip()
    parts = lang.split("+")
    have = set(installed_languages())
    if not parts or any(p not in have for p in parts) or len(parts) > 3:
        raise ExtractError("bad_language", f"Language '{lang}' is not installed on this server.")
    return "+".join(parts)


def tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except pytesseract.TesseractNotFoundError:
        raise ExtractError("ocr_unavailable",
                           "The OCR engine (Tesseract) is not installed on this server.", 503)
    except RuntimeError as e:
        if "timeout" in str(e).lower():
            raise ExtractError("ocr_timeout",
                               "This page took too long to read. Try a smaller or clearer file.", 504)
        raise


def ocr_words(gray: np.ndarray, lang: str, psm: Optional[int] = None) -> List[Word]:
    """Run Tesseract and return word boxes (pixel coordinates of `gray`)."""
    psm = psm or Config.OCR_PSM
    cfg = f"--oem 1 --psm {psm} -c tessedit_do_invert=0"
    d = _run(pytesseract.image_to_data, gray, lang=lang, config=cfg,
             output_type=Output.DICT, timeout=Config.OCR_TIMEOUT)
    words: List[Word] = []
    for i in range(len(d["text"])):
        txt = (d["text"][i] or "").strip()
        if not txt:
            continue
        try:
            conf = float(d["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < 0:
            continue
        x, y, w, h = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
        if w <= 0 or h <= 0:
            continue
        if conf < 15:
            continue                                    # almost certainly noise
        if _JUNK.match(txt) and (conf < 70 or w > 6 * h):
            continue                                    # stray grid / rule fragments
        words.append(Word(txt, x, y, x + w, y + h, conf))
    return words


def _score(words: List[Word]) -> float:
    """Expected number of correctly recognised characters."""
    return sum(w.conf / 100.0 * len(w.text) for w in words)


def ocr_page(gray: np.ndarray, lang: str) -> List[Word]:
    """OCR a whole page. Uses the preferred page mode, and only if the result looks unsure
    also tries the other mode (pictures / stamps can confuse one-block mode) and keeps the better."""
    first = Config.OCR_PSM
    words = ocr_words(gray, lang, psm=first)
    mean_conf = float(np.mean([w.conf for w in words])) if words else 0.0
    if mean_conf >= 80.0 and len(words) >= 3:
        return words
    alt = ocr_words(gray, lang, psm=3 if first != 3 else 6)
    return alt if _score(alt) > _score(words) else words


def ocr_crop(gray: np.ndarray, lang: str) -> Tuple[str, float]:
    """OCR one small cell image. Returns (text, mean confidence)."""
    import cv2
    h, w = gray.shape
    pad = cv2.copyMakeBorder(gray, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
    psm = 7 if h < 90 else 6
    words = ocr_words(pad, lang, psm=psm)
    if not words:
        return "", 0.0
    words.sort(key=lambda x: (round(x.cy / max(x.h, 1)), x.x0))
    text = " ".join(x.text for x in words)
    return text, float(np.mean([x.conf for x in words]))


def detect_rotation(gray: np.ndarray, lang: str = "eng") -> int:
    """Degrees (0/90/180/270, clockwise) needed to make the page upright; 0 if unsure."""
    import cv2
    h, w = gray.shape
    f = 1600.0 / max(h, w)
    small = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_AREA) if f < 1 else gray
    try:
        d = pytesseract.image_to_osd(small, config="--psm 0", output_type=Output.DICT, timeout=20)
        rot = int(d.get("rotate", 0))
        conf = float(d.get("orientation_conf", 0))
    except pytesseract.TesseractNotFoundError:
        raise ExtractError("ocr_unavailable",
                           "The OCR engine (Tesseract) is not installed on this server.", 503)
    except Exception:
        rot = 0
        conf = 0.0

    if rot in (90, 180, 270) and conf >= 4.0:
        return rot

    # Fallback: compare OCR readability across the likely orientations. This catches rotated
    # scans where OSD is inconclusive or the page text layout is unusual.
    best_rot = 0
    best_score = -1.0
    for candidate in (0, 90, 180, 270):
        candidate_gray = gray if candidate == 0 else imaging.rotate_by_osd(gray, candidate)
        words = ocr_words(candidate_gray, lang, psm=6)
        if not words:
            continue
        score = sum(w.conf / 100.0 * max(len(w.text), 1) for w in words)
        if score > best_score:
            best_score = score
            best_rot = candidate
    return best_rot if best_score > 0 else 0
