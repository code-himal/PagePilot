"""Table detection and cell assembly.

Two detectors feed the same output format:
  * ruled tables    - grid lines found by OpenCV (images) or pdfplumber (native PDFs)
  * aligned tables  - borderless tables found from whitespace between columns
"""
import re
from bisect import bisect_right
from typing import List, Optional, Tuple

import numpy as np

from .config import Config
from .geometry import Line, group_lines, median, runs_of, seg_text, split_segments
from .models import Word
from .textutil import clean_text

_LIST_MARKER = re.compile(r"^(?:[•●▪■◦·‣∙*–—-]|\d{1,3}[.)]|[a-zA-Z][.)])$")

Rows = List[List[str]]
Low = List[List[bool]]


# ----------------------------------------------------------------------------- helpers
def _norm(s: str) -> str:
    return " ".join(clean_text(s).split())


def join_cell(words: List[Word]) -> str:
    """Words that fall in one cell -> text (multi-line cells are joined with spaces)."""
    if not words:
        return ""
    lines = group_lines(words, native=False)
    return _norm(" ".join(l.text for l in lines))


def cell_is_low(words: List[Word]) -> bool:
    if not words:
        return False
    return float(np.mean([w.conf for w in words])) < Config.LOW_CONF


def tidy(rows: Rows, low: Optional[Low] = None) -> Tuple[Rows, Low]:
    """Make the table rectangular and drop rows / columns that are completely empty."""
    ncols = max((len(r) for r in rows), default=0)
    rows = [[_norm(c) for c in r] + [""] * (ncols - len(r)) for r in rows]
    if low is None:
        low = [[False] * ncols for _ in rows]
    else:
        low = [list(l) + [False] * (ncols - len(l)) for l in low]

    keep_r = [i for i, r in enumerate(rows) if any(c for c in r)]
    rows = [rows[i] for i in keep_r]
    low = [low[i] for i in keep_r]
    if not rows:
        return [], []
    keep_c = [j for j in range(ncols) if any(r[j] for r in rows)]
    rows = [[r[j] for j in keep_c] for r in rows]
    low = [[l[j] for j in keep_c] for l in low]
    return rows, low


def table_is_useful(rows: Rows) -> bool:
    """At least 2 rows x 2 columns and a meaningful share of filled cells."""
    if len(rows) < 2 or not rows or len(rows[0]) < 2:
        return False
    total = sum(len(r) for r in rows)
    filled = sum(1 for r in rows for c in r if c)
    return filled >= 4 and filled / max(total, 1) >= 0.25


# ----------------------------------------------------------------------------- ruled tables (images)
def fill_grid(grid: dict, words: List[Word]):
    """Assign OCR words to the cells of a detected grid.

    Returns (rows, low, redo, used_ids). `redo` lists cells worth a second, per-cell OCR pass as
    (r, c, x0, y0, x1, y1, old_conf): cells that got no words (old_conf None) and cells whose
    words had low confidence.
    """
    xs, ys = grid["xs"], grid["ys"]
    nr, nc = len(ys) - 1, len(xs) - 1
    buckets = [[[] for _ in range(nc)] for _ in range(nr)]
    used = set()
    for w in words:
        cx, cy = w.cx, w.cy
        if not (xs[0] <= cx <= xs[-1] and ys[0] <= cy <= ys[-1]):
            continue
        c = min(max(bisect_right(xs, cx) - 1, 0), nc - 1)
        r = min(max(bisect_right(ys, cy) - 1, 0), nr - 1)
        buckets[r][c].append(w)
        used.add(id(w))

    rows = [[join_cell(b) for b in row] for row in buckets]
    low = [[cell_is_low(b) for b in row] for row in buckets]
    redo = []
    for r in range(nr):
        for c in range(nc):
            b = buckets[r][c]
            if not b:
                redo.append((r, c, xs[c], ys[r], xs[c + 1], ys[r + 1], None))
            elif low[r][c]:
                redo.append((r, c, xs[c], ys[r], xs[c + 1], ys[r + 1], float(np.mean([w.conf for w in b]))))
    return rows, low, redo, used


def grid_bbox(grid: dict):
    return (grid["xs"][0], grid["ys"][0], grid["xs"][-1], grid["ys"][-1])


# ----------------------------------------------------------------------------- aligned (borderless) tables
def find_aligned_tables(words: List[Word], native: bool):
    """Find borderless tables from column whitespace.

    Returns a list of {"rows", "low", "used", "y0"} where `used` is a set of id(word).
    """
    lines = group_lines(words, native)
    if len(lines) < 3:
        return []
    h_med = median(l.h for l in lines)
    if h_med <= 0:
        return []
    gap = 1.4 * h_med
    seg_lists = [split_segments(l, gap) for l in lines]
    multi = [len(s) >= 2 for s in seg_lists]

    # 1. runs of consecutive multi-segment lines (one single-segment "bridge" line allowed).
    #    A run ends at a vertical gap that is large compared with the run's own row spacing.
    def pitch_limit(cur):
        pitches = [lines[b].cy - lines[a].cy for a, b in zip(cur, cur[1:])]
        if not pitches:
            return 5.0 * h_med
        return max(2.6 * h_med, 1.6 * median(pitches))

    runs, cur = [], []
    for i in range(len(lines)):
        if cur and lines[i].cy - lines[cur[-1]].cy > pitch_limit(cur):
            runs.append(cur)
            cur = []
        if multi[i]:
            cur.append(i)
            continue
        # single-segment line: allowed as a bridge if the next line is multi-segment and close
        if (cur and cur[-1] == i - 1 and i + 1 < len(lines) and multi[i + 1]
                and (lines[i + 1].cy - lines[i].cy) <= pitch_limit(cur)):
            cur.append(i)
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)

    tables = []
    for run in runs:
        while run and not multi[run[-1]]:               # never end on a bridge
            run = run[:-1]
        if sum(1 for i in run if multi[i]) < 3:
            continue
        t = _build_aligned(run, lines, seg_lists, h_med)
        if t:
            tables.append(t)
    return tables


def _build_aligned(run, lines: List[Line], seg_lists, h_med: float):
    segs_by_line = [seg_lists[i] for i in run]
    xmin = min(min(w.x0 for w in s) for segs in segs_by_line for s in segs)
    xmax = max(max(w.x1 for w in s) for segs in segs_by_line for s in segs)
    width = int(np.ceil(xmax - xmin)) + 2
    if width < 10:
        return None

    cov = np.zeros(width, dtype=np.int32)
    for segs in segs_by_line:
        for s in segs:
            a = int(min(w.x0 for w in s) - xmin)
            b = int(max(w.x1 for w in s) - xmin) + 1
            cov[a:b] += 1
    tol = int(0.12 * len(run))                          # tolerate a few rows that span columns
    covered = cov > tol
    min_channel = max(0.6 * h_med, 3.0)

    # covered spans, merged when the hole between them is narrower than a real column gutter
    spans = []
    for a, b in runs_of(covered):
        if spans and a - spans[-1][1] < min_channel:
            spans[-1] = (spans[-1][0], b)
        else:
            spans.append((a, b))
    if not (2 <= len(spans) <= 30):
        return None

    def col_of(cx: float) -> int:
        x = cx - xmin
        best, best_d = 0, float("inf")
        for j, (a, b) in enumerate(spans):
            if a <= x < b:
                return j
            d = min(abs(x - a), abs(x - b))
            if d < best_d:
                best, best_d = j, d
        return best

    rows: Rows = []
    low: Low = []
    used = set()
    for segs in segs_by_line:
        cells = [[] for _ in spans]
        for s in segs:
            cx = (min(w.x0 for w in s) + max(w.x1 for w in s)) / 2.0
            cells[col_of(cx)].append(s)
        rows.append([_norm(" ".join(seg_text(s) for s in c)) for c in cells])
        low.append([bool(c) and float(np.mean([w.conf for s in c for w in s])) < Config.LOW_CONF for c in cells])
        for s in segs:
            for w in s:
                used.add(id(w))

    n_rows = len(rows)
    multi_rows = sum(1 for r in rows if sum(1 for c in r if c) >= 2)
    if multi_rows < 3 or multi_rows / n_rows < 0.6:
        return None
    filled = [c for r in rows for c in r if c]
    if not filled or float(np.mean([len(c.split()) for c in filled])) > 4.0:
        return None                                     # prose in columns, not a table
    if len(spans) == 2:
        keyish = sum(1 for r in rows if r[0].endswith(":"))
        if keyish / n_rows >= 0.7:
            return None                                 # "Label:  value" form fields, not a table
        col_means = [np.mean([len(r[j].split()) for r in rows if r[j]] or [0]) for j in (0, 1)]
        if min(col_means) >= 3.5:
            return None                                 # two columns of running text
    first_col = [r[0] for r in rows if r[0]]
    if first_col and sum(1 for c in first_col if _LIST_MARKER.match(c)) / n_rows >= 0.7:
        return None                                     # a bullet / numbered list, not a table
    if (len(first_col) >= 3 and len({c.lower() for c in first_col}) == 1 and len(first_col[0]) <= 2
            and not first_col[0].isdigit()):
        return None                                     # same 1-2 characters on every row = OCR'd bullets

    rows, low = tidy(rows, low)
    if not table_is_useful(rows):
        return None
    y0 = min(lines[i].y0 for i in run)
    y1 = max(lines[i].y1 for i in run)
    return {"rows": rows, "low": low, "used": used, "y0": y0, "y1": y1}
