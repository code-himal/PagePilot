"""Central configuration. Every value can be overridden with an environment variable."""
import os
import shutil
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _detect_tesseract() -> str:
    env = os.getenv("TESSERACT_CMD")
    if env and os.path.exists(env):
        return env

    found = shutil.which("tesseract") or shutil.which("tesseract.exe")
    if found:
        return found

    for candidate in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if os.path.exists(candidate):
            return candidate

    return ""


def _ensure_path(bin_dir: str) -> None:
    if not bin_dir:
        return
    entries = [e for e in os.environ.get("PATH", "").split(os.pathsep) if e]
    if bin_dir not in entries:
        os.environ["PATH"] = os.pathsep.join([bin_dir, *entries])


def _detect_poppler() -> str:
    found = shutil.which("pdftoppm") or shutil.which("pdftoppm.exe")
    if found:
        return str(Path(found).parent)

    for base in (
        Path(r"C:\Users\acer\AppData\Local\Microsoft\WinGet\Packages"),
        Path(r"C:\Program Files"),
        Path(r"C:\Program Files (x86)"),
    ):
        if not base.exists():
            continue
        for match in base.rglob("pdftoppm.exe"):
            return str(match.parent)
    return ""


TESSERACT_CMD = _detect_tesseract()
if TESSERACT_CMD:
    os.environ["TESSERACT_CMD"] = TESSERACT_CMD
    _ensure_path(str(Path(TESSERACT_CMD).parent))

POPPER_BIN = _detect_poppler()
if POPPER_BIN:
    _ensure_path(POPPER_BIN)


class Config:
    # Upload limits
    MAX_UPLOAD_MB = _int("DOCPIXLY_MAX_UPLOAD_MB", 20)
    MAX_PAGES = _int("DOCPIXLY_MAX_PAGES", 25)          # pages processed per file
    MAX_IMAGE_PIXELS = _int("DOCPIXLY_MAX_IMAGE_PIXELS", 60_000_000)
    MAX_EXPORT_MB = _int("DOCPIXLY_MAX_EXPORT_MB", 10)   # size of JSON posted to /api/export
    MAX_EXPORT_CELLS = _int("DOCPIXLY_MAX_EXPORT_CELLS", 500_000)

    MAX_CONCURRENT = _int("DOCPIXLY_MAX_CONCURRENT", 2)  # simultaneous extractions per server process

    # OCR / rendering
    OCR_DPI = _int("DOCPIXLY_OCR_DPI", 300)              # DPI used to rasterise PDF pages
    OCR_TIMEOUT = _int("DOCPIXLY_OCR_TIMEOUT", 90)       # seconds per Tesseract call
    OCR_PSM = _int("DOCPIXLY_OCR_PSM", 6)                # first-choice Tesseract page mode (6 = one block, best for tables)
    MAX_SIDE_PX = _int("DOCPIXLY_MAX_SIDE_PX", 5200)     # longest side of an OCR image
    TESSERACT_CMD = TESSERACT_CMD                         # set on Windows if not on PATH

    # Preview thumbnails returned to the browser
    PREVIEW_PAGES = _int("DOCPIXLY_PREVIEW_PAGES", 8)
    PREVIEW_WIDTH = _int("DOCPIXLY_PREVIEW_WIDTH", 900)

    # Confidence below which a table cell is highlighted for review
    LOW_CONF = _int("DOCPIXLY_LOW_CONF", 65)
