"""Orchestration: file -> pages -> words -> tables + text blocks -> JSON-serialisable result."""
import base64
import io
import re
import time
from typing import List, Optional, Tuple

import cv2
import numpy as np
import pdfplumber
import pypdfium2 as pdfium
from PIL import Image

from . import imaging, ocr
from .config import Config
from .errors import ExtractError
from .layout import analyze_words
from .models import Word
from .tables import (fill_grid, grid_bbox, table_is_useful, tidy, _norm)
from .textutil import clean_text

Image.MAX_IMAGE_PIXELS = None            # we enforce our own limit explicitly (see _open_image)

_BOLD_RE = re.compile(r"bold|black|heavy|semibold|demi", re.I)


# ----------------------------------------------------------------------------- input handling
def sniff_type(path: str) -> Optional[str]:
    """Identify the file by its content, never by its extension."""
    with open(path, "rb") as f:
        head = f.read(1024)
    if b"%PDF-" in head:
        return "pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"
    if head.startswith(b"\xff\xd8\xff"):
        return "image"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image"
    if head[:2] == b"BM":
        return "image"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "image"
    return None


def parse_page_ranges(spec: str, total: int) -> List[int]:
    """'1-3,5,8-' -> [0,1,2,4,7,...] (zero-based, sorted, unique, clipped to the document)."""
    spec = (spec or "").strip()
    if not spec:
        return list(range(total))
    picked = set()
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d*))?", part)
        if not m:
            raise ExtractError("bad_pages", f"Page selection '{spec}' is not valid. Use something like 1-3,5.")
        a = int(m.group(1))
        if m.group(2) is None:
            b = a
        elif m.group(2) == "":
            b = total
        else:
            b = int(m.group(2))
        if a < 1 or b < a:
            raise ExtractError("bad_pages", f"Page selection '{spec}' is not valid. Use something like 1-3,5.")
        picked.update(range(a, min(b, total) + 1))
    picked = {p - 1 for p in picked if 1 <= p <= total}
    if not picked:
        raise ExtractError("bad_pages", f"The file has {total} page(s); none match '{spec}'.")
    return sorted(picked)


def _thumb(gray: np.ndarray) -> str:
    h, w = gray.shape
    f = Config.PREVIEW_WIDTH / float(w)
    small = cv2.resize(gray, (Config.PREVIEW_WIDTH, max(1, int(h * f))),
                       interpolation=cv2.INTER_AREA) if f < 1 else gray
    ok, buf = cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii") if ok else ""


# ----------------------------------------------------------------------------- OCR of one raster page
def _analyze_raster(gray: np.ndarray, lang: str):
    """Grid detection + line removal + OCR + layout for an already-normalised page image."""
    grids, mask = imaging.find_grid_tables(gray)
    ocr_img = gray.copy()
    if grids:
        ocr_img[mask > 0] = 255
    words = ocr.ocr_page(ocr_img, lang)

    ruled, used = [], set()
    for grid in grids:
        rows, low, redo, u = fill_grid(grid, words)
        budget = 40
        for r, c, x0, y0, x1, y1, old_conf in redo:      # re-read empty / uncertain cells one by one
            if budget <= 0:
                break
            crop = ocr_img[int(y0) + 4:int(y1) - 4, int(x0) + 4:int(x1) - 4]
            if crop.shape[0] < 10 or crop.shape[1] < 10:
                continue
            if old_conf is None:                          # empty cell: only if there is visible ink
                ink = int((crop < 160).sum())
                if ink < 30 or ink / crop.size < 0.004:
                    continue
            budget -= 1
            text, conf = ocr.ocr_crop(crop, lang)
            if text and (old_conf is None or conf > old_conf):
                rows[r][c] = _norm(text)
                low[r][c] = conf < Config.LOW_CONF
        rows, low = tidy(rows, low)
        if table_is_useful(rows):
            ruled.append({"rows": rows, "low": low, "y0": grid_bbox(grid)[1], "y1": grid_bbox(grid)[3]})
            used |= u

    rest = [w for w in words if id(w) not in used]
    blocks, fields = analyze_words(rest, ruled, native=False)
    return blocks, fields, words


def process_raster_page(gray: np.ndarray, lang: str):
    """Normalise a page image, OCR it, and return (blocks, fields, confidence, upright_gray)."""
    gray = imaging.limit_size(gray, Config.MAX_SIDE_PX)
    gray = imaging.ensure_dark_on_light(gray)
    rot = ocr.detect_rotation(gray, lang)
    if rot:
        gray = imaging.rotate_by_osd(gray, rot)
    gray = imaging.flatten_background(gray)
    gray = imaging.deskew(gray)
    gray = imaging.scale_for_ocr(gray, Config.MAX_SIDE_PX)

    blocks, fields, words = _analyze_raster(gray, lang)

    if len(words) >= 10:                                   # text too small for Tesseract? retry bigger
        med_h = float(np.median([w.h for w in words]))
        f = min(3.0, 28.0 / max(med_h, 1.0))
        if med_h < 20 and f > 1.3 and max(gray.shape) * f <= Config.MAX_SIDE_PX:
            gray = imaging.resize_factor(gray, f)
            blocks, fields, words = _analyze_raster(gray, lang)

    conf = float(np.mean([w.conf for w in words])) if words else None
    return blocks, fields, conf, gray


# ----------------------------------------------------------------------------- native PDF page
def _native_words(plpage) -> List[Word]:
    raw = plpage.extract_words(x_tolerance=2, y_tolerance=3, keep_blank_chars=False,
                               use_text_flow=False, extra_attrs=["size", "fontname"])
    words = []
    for r in raw:
        text = clean_text(r.get("text", "")).replace("(cid:127)", "•").strip()   # bullet glyph of standard fonts
        if not text:
            continue
        size = float(r.get("size") or 0.0) or max(r["bottom"] - r["top"], 1.0)
        words.append(Word(text, r["x0"], r["top"], r["x1"], r["bottom"], 100.0, size,
                          bool(_BOLD_RE.search(str(r.get("fontname", ""))))))
    return words


def _looks_native(words: List[Word]) -> bool:
    """Does this page have a usable text layer (as opposed to a scanned picture)?"""
    if len(words) < 8:
        return False
    text = " ".join(w.text for w in words)
    if len(text) < 40:
        return False
    if text.count("(cid:") / max(len(words), 1) > 0.05 or text.count("\ufffd") / max(len(text), 1) > 0.02:
        return False                                       # broken font encoding -> OCR is better
    letters = sum(ch.isalnum() for ch in text)
    return letters / max(len(text), 1) > 0.4


def _native_ruled_tables(plpage) -> Tuple[List[dict], List[Tuple[float, float, float, float]]]:
    ruled, boxes = [], []
    try:
        found = plpage.find_tables(table_settings={
            "vertical_strategy": "lines", "horizontal_strategy": "lines",
            "snap_tolerance": 3, "join_tolerance": 3, "edge_min_length": 8})
    except Exception:
        return [], []
    for t in found:
        try:
            raw = t.extract(x_tolerance=2, y_tolerance=3)
        except Exception:
            continue
        rows = [[_norm(c or "") for c in r] for r in raw]
        rows, low = tidy(rows)
        if table_is_useful(rows):
            ruled.append({"rows": rows, "low": low, "y0": t.bbox[1], "y1": t.bbox[3]})
            boxes.append(t.bbox)
    return ruled, boxes


def _process_native_page(plpage, words: List[Word]):
    ruled, boxes = _native_ruled_tables(plpage)
    if boxes:
        def inside(w: Word) -> bool:
            return any(b[0] - 1 <= w.cx <= b[2] + 1 and b[1] - 1 <= w.cy <= b[3] + 1 for b in boxes)
        words = [w for w in words if not inside(w)]
    blocks, fields = analyze_words(words, ruled, native=True)
    return blocks, fields


def _render_pdf_page(pdoc, index: int) -> Image.Image:
    page = pdoc[index]
    w_pt, h_pt = page.get_size()
    scale = min(Config.OCR_DPI / 72.0, Config.MAX_SIDE_PX / max(w_pt, h_pt, 1.0))
    return page.render(scale=scale).to_pil()


def _pdf_preview(pdoc, index: int) -> str:
    page = pdoc[index]
    w_pt, _ = page.get_size()
    pil = page.render(scale=max(Config.PREVIEW_WIDTH / max(w_pt, 1.0), 0.3)).to_pil()
    return _thumb(imaging.pil_to_gray(pil))


# ----------------------------------------------------------------------------- public entry point
def extract_document(path: str, original_name: str, lang: str = "eng", mode: str = "auto",
                     pages_spec: str = "") -> dict:
    t0 = time.time()
    kind = sniff_type(path)
    if kind is None:
        raise ExtractError("unsupported", "Unsupported file. Upload a PDF, JPG, PNG, WEBP, BMP or TIFF.", 415)
    if mode not in ("auto", "ocr"):
        mode = "auto"
    if ocr.installed_languages():
        lang = ocr.validate_lang(lang)

    if kind == "pdf":
        result = _extract_pdf(path, lang, mode, pages_spec)
    else:
        result = _extract_image(path, lang, pages_spec)

    all_fields, seen = [], set()
    for pg in result["pages"]:
        for k, v in pg.pop("_fields"):
            if (k, v) not in seen:
                seen.add((k, v))
                all_fields.append({"key": k, "value": v, "page": pg["number"]})
        tn = 0
        for b in pg["blocks"]:
            if b["type"] == "table":
                tn += 1
                b["id"] = f"p{pg['number']}t{tn}"
    n_tables = sum(1 for pg in result["pages"] for b in pg["blocks"] if b["type"] == "table")
    n_chars = sum(len(b.get("text", "")) for pg in result["pages"] for b in pg["blocks"])
    result.update({
        "filename": clean_text(original_name)[:200] or "document",
        "kind": kind,
        "language": lang,
        "fields": all_fields if len(all_fields) >= 2 else [],
        "stats": {"pages": len(result["pages"]), "tables": n_tables, "characters": n_chars,
                  "seconds": round(time.time() - t0, 1)},
    })
    return result


def _page_dict(number, method, blocks, fields, conf, preview, w, h, warnings=None):
    if not blocks:
        warnings = (warnings or []) + ["No text was found on this page."]
    return {"number": number, "method": method, "width": int(w), "height": int(h),
            "confidence": None if conf is None else round(conf, 1),
            "preview": preview, "blocks": blocks, "warnings": warnings or [], "_fields": fields}


def _extract_pdf(path: str, lang: str, mode: str, pages_spec: str) -> dict:
    try:
        plpdf = pdfplumber.open(path)
        pdoc = pdfium.PdfDocument(path)
    except Exception as e:                                   # noqa: BLE001 - map to a friendly message
        msg = str(e).lower()
        if "password" in msg or "encrypt" in msg:
            raise ExtractError("encrypted", "This PDF is password-protected. Remove the password and try again.")
        raise ExtractError("bad_pdf", "This PDF could not be opened. The file may be damaged.")
    warnings = []
    try:
        total = len(plpdf.pages)
        if total == 0:
            raise ExtractError("bad_pdf", "This PDF has no pages.")
        sel = parse_page_ranges(pages_spec, total)
        if len(sel) > Config.MAX_PAGES:
            warnings.append(f"Only the first {Config.MAX_PAGES} of the {len(sel)} selected pages were processed.")
            sel = sel[:Config.MAX_PAGES]

        pages = []
        for k, idx in enumerate(sel):
            plpage = plpdf.pages[idx]
            words = [] if mode == "ocr" else _native_words(plpage)
            if mode != "ocr" and _looks_native(words):
                blocks, fields = _process_native_page(plpage, words)
                preview = _pdf_preview(pdoc, idx) if k < Config.PREVIEW_PAGES else ""
                pages.append(_page_dict(idx + 1, "text", blocks, fields, None, preview,
                                        plpage.width, plpage.height))
            else:
                pil = _render_pdf_page(pdoc, idx)
                blocks, fields, conf, gray = process_raster_page(imaging.pil_to_gray(pil), lang)
                preview = _thumb(gray) if k < Config.PREVIEW_PAGES else ""
                pages.append(_page_dict(idx + 1, "ocr", blocks, fields, conf, preview,
                                        gray.shape[1], gray.shape[0]))
        return {"pages": pages, "total_pages": total, "warnings": warnings}
    finally:
        try:
            plpdf.close()
        finally:
            pdoc.close()


def _extract_image(path: str, lang: str, pages_spec: str) -> dict:
    try:
        im = Image.open(path)
        im.load() if getattr(im, "n_frames", 1) == 1 else None
    except Exception:
        raise ExtractError("bad_image", "This image could not be opened. The file may be damaged.")
    warnings = []
    try:
        if im.size[0] * im.size[1] > Config.MAX_IMAGE_PIXELS:
            raise ExtractError("too_large", "This image has too many pixels. Please use a smaller photo or scan.", 413)
        total = getattr(im, "n_frames", 1)
        sel = parse_page_ranges(pages_spec, total) if total > 1 else [0]
        if len(sel) > Config.MAX_PAGES:
            warnings.append(f"Only the first {Config.MAX_PAGES} of the {len(sel)} selected pages were processed.")
            sel = sel[:Config.MAX_PAGES]
        pages = []
        for k, idx in enumerate(sel):
            try:
                im.seek(idx)
                frame = im.copy()
            except Exception:
                raise ExtractError("bad_image", "This image could not be read. The file may be damaged.")
            blocks, fields, conf, gray = process_raster_page(imaging.pil_to_gray(frame), lang)
            preview = _thumb(gray) if k < Config.PREVIEW_PAGES else ""
            pages.append(_page_dict(idx + 1, "ocr", blocks, fields, conf, preview,
                                    gray.shape[1], gray.shape[0]))
        return {"pages": pages, "total_pages": total, "warnings": warnings}
    finally:
        im.close()
