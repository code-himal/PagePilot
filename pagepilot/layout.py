"""Reading-order reconstruction: columns -> paragraphs -> headings / lists / fields.

Works on word boxes only, so the same code serves OCR pages and native PDF pages.
"""
import re
from typing import Dict, List, Tuple

import numpy as np

from .geometry import Line, group_lines, median, seg_text, split_segments
from .models import Word
from .tables import find_aligned_tables, tidy

BULLET_RE = re.compile(r"^\s*([•●▪■◦·‣∙*–—-])\s+(?=\S)")
FIELD_RE = re.compile(r"^\s*([^\W\d_][\w .#/&()'\-]{0,38}?)\s*[:：]\s+(\S.{0,200})$", re.UNICODE)
_NOT_KEYS = {"http", "https", "ftp", "mailto"}


# ----------------------------------------------------------------------------- columns
def split_flows(lines: List[Line]) -> List[List[Line]]:
    """Split a page into reading flows. Handles the common two-column layout; otherwise one flow."""
    n = len(lines)
    if n < 10:
        return [lines]
    xmin = min(l.x0 for l in lines)
    xmax = max(l.x1 for l in lines)
    span = xmax - xmin
    if span < 50:
        return [lines]
    h_med = median(l.h for l in lines)

    width = int(span) + 2
    cov = np.zeros(width, dtype=np.int32)
    for l in lines:
        for w in l.words:
            cov[int(w.x0 - xmin):int(w.x1 - xmin) + 1] += 1

    lo, hi = int(0.25 * span), int(0.75 * span)
    free = cov <= max(1, int(0.12 * n))
    best = None
    i = lo
    while i < hi:
        if free[i]:
            j = i
            while j < hi and free[j]:
                j += 1
            if best is None or (j - i) > (best[1] - best[0]):
                best = (i, j)
            i = j
        else:
            i += 1
    if best is None or (best[1] - best[0]) < max(2.0 * h_med, 0.025 * span):
        return [lines]
    c = xmin + (best[0] + best[1]) / 2.0

    def spans_channel(l: Line) -> bool:
        return any(w.x0 < c < w.x1 for w in l.words)

    spanning = [spans_channel(l) for l in lines]
    if sum(spanning) > 0.15 * n:
        return [lines]

    left_lines = [l for l, s in zip(lines, spanning) if not s and l.x1 <= c]
    right_lines = [l for l, s in zip(lines, spanning) if not s and l.x0 >= c]
    both = [l for l, s in zip(lines, spanning) if not s]
    # prose check: each side must have real, wide-ish text (not a key/value form)
    def looks_prose(side: List[Line]) -> bool:
        if len(side) < 5:
            return False
        return float(np.mean([len(l.words) for l in side])) >= 4.0
    l_side = [w for l in both for w in l.words if w.x1 <= c]
    r_side = [w for l in both for w in l.words if w.x0 >= c]
    if not l_side or not r_side:
        return [lines]
    left_l = group_lines(l_side, native=lines[0].words[0].size > 0)
    right_l = group_lines(r_side, native=lines[0].words[0].size > 0)
    if not (looks_prose(left_l) and looks_prose(right_l)):
        return [lines]

    native = lines[0].words[0].size > 0
    flows: List[List[Line]] = []
    run: List[Line] = []
    left_acc: List[Word] = []
    right_acc: List[Word] = []

    def flush_region():
        nonlocal left_acc, right_acc
        if left_acc:
            flows.append(group_lines(left_acc, native))
        if right_acc:
            flows.append(group_lines(right_acc, native))
        left_acc, right_acc = [], []

    def flush_run():
        nonlocal run
        if run:
            flows.append(run)
        run = []

    for l, s in zip(lines, spanning):
        if s:
            flush_region()
            run.append(l)
        else:
            flush_run()
            for w in l.words:
                (left_acc if w.x1 <= c else right_acc).append(w)
    flush_region()
    flush_run()
    return [f for f in flows if f]


# ----------------------------------------------------------------------------- paragraphs
def _is_upperish(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    return len(letters) >= 3 and sum(ch.isupper() for ch in letters) / len(letters) >= 0.8


def _eff_h(line: Line, native: bool) -> float:
    # ALL-CAPS text has no ascenders/descenders so its box is shorter for the same point size
    return line.h if native or not _is_upperish(line.text) else line.h * 1.3


def _crosses(barriers: List[float], a: Line, b: Line) -> bool:
    """Is there a table (or other removed block) between these two consecutive lines?"""
    return any(a.cy < y < b.cy for y in barriers)


def build_paragraphs(lines: List[Line], native: bool, body_h: float, barriers: List[float] = (),
                     body_cw: float = 0.0) -> List[dict]:
    """Group the lines of one reading flow into paragraphs, headings and list items."""
    if not lines:
        return []
    left_edge = float(np.percentile([l.x0 for l in lines], 10))
    right_edge = float(np.percentile([l.x1 for l in lines], 90))
    span = max(right_edge - left_edge, 1.0)

    # normal line pitch = lower quartile of pitches between similar-sized consecutive lines
    pitches = []
    for a, b in zip(lines, lines[1:]):
        if 0.8 <= (b.h / max(a.h, 0.01)) <= 1.25 and not _crosses(barriers, a, b):
            pitches.append(b.cy - a.cy)
    p0 = float(np.percentile(pitches, 30)) if pitches else 1.25 * body_h
    p0 = max(p0, 0.6 * body_h)

    groups: List[List[Line]] = []
    for line in lines:
        start_new = True
        if groups:
            prev = groups[-1][-1]
            first = groups[-1][0]
            pitch = line.cy - prev.cy
            ratio = line.h / max(prev.h, 0.01)
            bullet = bool(BULLET_RE.match(line.text))
            same_size = 0.82 <= ratio <= 1.22
            if same_size and not native and body_cw > 0:
                same_size = 0.8 <= line.cw / max(prev.cw, 0.01) <= 1.25
            indented = (line.x0 - first.x0) > 1.2 * body_h and abs(prev.x0 - first.x0) < 0.6 * body_h and len(groups[-1]) >= 1
            outdented = (first.x0 - line.x0) > 0.8 * body_h
            bold_change = native and (line.bold != prev.bold)
            start_new = (_crosses(barriers, prev, line) or
                         not (pitch <= 1.35 * p0 and same_size and not bullet and not indented
                              and not outdented and not bold_change))
        if start_new:
            groups.append([line])
        else:
            groups[-1].append(line)

    out = []
    for g in groups:
        text_lines = [l.text for l in g]
        y0 = min(l.y0 for l in g)
        x0 = min(l.x0 for l in g)
        first = g[0]
        bullet = BULLET_RE.match(first.text)

        # heading?
        gh = float(np.mean([_eff_h(l, native) for l in g]))
        ratio = gh / max(body_h, 0.01)
        if not native and body_cw > 0 and ratio >= 0.92:
            # Bigger / bolder type has wider glyphs even when the box height is misleading
            # (e.g. a title without descenders). Discount ~8% for bold letter shapes.
            ratio = max(ratio, float(np.mean([l.cw for l in g])) / body_cw / 1.08)
        joined_len = sum(len(t) for t in text_lines)
        level = 0
        thr = 1.12 if native else 1.28
        if len(g) <= 2 and joined_len <= 140 and not bullet:
            if ratio >= thr:
                level = 1 if ratio >= 1.75 else 2 if ratio >= 1.3 else 3
            elif (native and len(g) == 1 and all(l.bold for l in g) and joined_len <= 90
                  and not text_lines[0].rstrip().endswith((".", ":", ","))):
                level = 3
        if level:
            out.append({"type": "heading", "level": level, "text": " ".join(text_lines), "_y0": y0, "_x0": x0})
            continue

        if bullet:
            g0 = re.sub(BULLET_RE, "", first.text, count=1)
            text = _join_lines([g0] + text_lines[1:])
            out.append({"type": "list_item", "text": text, "_y0": y0, "_x0": x0})
            continue

        # keep the line breaks of short-line blocks (addresses, form lines, signatures)
        keep_breaks = False
        if len(g) >= 2:
            full = [l for l in g[:-1] if l.x1 >= right_edge - 0.10 * span]
            keep_breaks = len(full) < 0.5 * (len(g) - 1)
        text = "\n".join(text_lines) if keep_breaks else _join_lines(text_lines)
        out.append({"type": "paragraph", "text": text, "_y0": y0, "_x0": x0})
    return out


def _join_lines(parts: List[str]) -> str:
    """Join wrapped lines, repairing words hyphenated at the line end."""
    text = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not text:
            text = p
        elif re.search(r"[A-Za-z]{2,}-$", text) and p[:1].islower():
            text = text[:-1] + p
        else:
            text += " " + p
    return text


# ----------------------------------------------------------------------------- fields
def extract_fields(lines: List[Line], gap: float) -> List[Tuple[str, str]]:
    """'Name: Himal Shrestha' style pairs. Handles several pairs on one line and wide gaps."""
    found = []
    for line in lines:
        if len(line.text) > 160:
            continue
        segs = [seg_text(s) for s in split_segments(line, gap)]
        i = 0
        while i < len(segs):
            s = segs[i].strip()
            m = FIELD_RE.match(s)
            if m and len(m.group(1).split()) <= 5 and m.group(1).strip().lower() not in _NOT_KEYS:
                found.append((m.group(1).strip(), m.group(2).strip()))
            elif (s.endswith((":", "：")) and 1 < len(s) <= 41 and i + 1 < len(segs)
                  and not segs[i + 1].strip().endswith((":", "："))
                  and len(s[:-1].split()) <= 5 and s[:1].isalpha()):
                found.append((s[:-1].strip(), segs[i + 1].strip()))
                i += 1
            i += 1
    return found


# ----------------------------------------------------------------------------- OCR bullet repair
_OCR_BULLET_CHARS = {"e", "o", "O", "°", "¢", "©", "«", "»", "®", "+", "©"}


def fix_ocr_bullets(lines: List[Line]) -> None:
    """OCR often reads a bullet dot as 'e', 'o', '°' ... Repair it when at least two lines start with
    the same lone character at the same indent, followed by a visible gap (a real bullet layout)."""
    cands = {}
    for l in lines:
        if len(l.words) < 2:
            continue
        a, b = l.words[0], l.words[1]
        if a.text in _OCR_BULLET_CHARS and a.w <= 1.3 * l.h and (b.x0 - a.x1) >= 0.3 * l.h:
            cands.setdefault(a.text, []).append(l)
    for char, group in cands.items():
        clusters = []
        for l in group:
            for cl in clusters:
                if abs(cl[0].x0 - l.x0) <= 0.6 * l.h:
                    cl.append(l)
                    break
            else:
                clusters.append([l])
        for cl in clusters:
            if len(cl) >= 2:
                for l in cl:
                    l.text = "• " + " ".join(w.text for w in l.words[1:])


# ----------------------------------------------------------------------------- page assembly
def analyze_words(words: List[Word], ruled: List[dict], native: bool) -> Tuple[List[dict], List[Tuple[str, str]]]:
    """Turn the words that are NOT inside ruled tables into ordered blocks.

    `ruled` is a list of {"rows","low","y0"} for tables already extracted by the caller.
    Returns (blocks, fields). Blocks carry temporary `_y0` keys that the caller strips.
    """
    tables = [dict(t, type="table", kind="ruled") for t in ruled]

    aligned = find_aligned_tables(words, native) if words else []
    used = set()
    for t in aligned:
        used |= t["used"]
        tables.append({"type": "table", "kind": "aligned", "rows": t["rows"], "low": t["low"],
                       "y0": t["y0"], "y1": t["y1"]})
    rest = [w for w in words if id(w) not in used]

    lines = group_lines(rest, native)
    if not native:
        fix_ocr_bullets(lines)
    paragraphs: List[dict] = []
    fields: List[Tuple[str, str]] = []
    if lines:
        body_h = _body_height(lines, native)
        body_cw = _body_char_width(lines)
        gap = 1.4 * body_h
        barriers = [(t["y0"] + t.get("y1", t["y0"])) / 2.0 for t in tables]
        for flow in split_flows(lines):
            paragraphs.extend(build_paragraphs(flow, native, body_h, barriers, body_cw))
            fields.extend(extract_fields(flow, gap))

    # merge tables into the paragraph sequence by vertical position
    tables.sort(key=lambda t: t["y0"])
    blocks: List[dict] = []
    ti = 0
    for p in paragraphs:
        while ti < len(tables) and tables[ti]["y0"] <= p["_y0"]:
            blocks.append(_table_block(tables[ti]))
            ti += 1
        blocks.append({k: v for k, v in p.items() if not k.startswith("_")})
    while ti < len(tables):
        blocks.append(_table_block(tables[ti]))
        ti += 1
    return blocks, fields


def _table_block(t: dict) -> dict:
    rows, low = tidy(t["rows"], t.get("low"))
    return {"type": "table", "kind": t.get("kind", "ruled"), "rows": rows, "low": low, "header": True}


def _body_height(lines: List[Line], native: bool) -> float:
    """Typical text height: median line height weighted by amount of text."""
    hs, ws = [], []
    for l in lines:
        hs.append(l.h)
        ws.append(max(len(l.text), 1))
    order = np.argsort(hs)
    hs = np.array(hs)[order]
    ws = np.array(ws)[order]
    cum = np.cumsum(ws)
    return float(hs[np.searchsorted(cum, cum[-1] / 2.0)])


def _body_char_width(lines: List[Line]) -> float:
    """Typical average glyph width (text-weighted median)."""
    cws = np.array([l.cw for l in lines])
    ws = np.array([max(len(l.text), 1) for l in lines])
    order = np.argsort(cws)
    cum = np.cumsum(ws[order])
    return float(cws[order][np.searchsorted(cum, cum[-1] / 2.0)])
