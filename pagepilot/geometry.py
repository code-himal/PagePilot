"""Line / segment grouping on word boxes. Used by both table detection and the layout engine."""
from typing import List

import numpy as np

from .models import Word


def median(values, default: float = 0.0) -> float:
    values = list(values)
    return float(np.median(values)) if values else default


class Line:
    """A horizontal run of words that share (roughly) the same baseline."""

    def __init__(self, words: List[Word], native: bool):
        self.words = sorted(words, key=lambda w: w.x0)
        self.x0 = min(w.x0 for w in self.words)
        self.x1 = max(w.x1 for w in self.words)
        self.y0 = min(w.y0 for w in self.words)
        self.y1 = max(w.y1 for w in self.words)
        self.cy = median(w.cy for w in self.words)
        if native:
            sizes = [w.size for w in self.words if w.size > 0] or [w.h for w in self.words]
            self.h = float(np.median(sizes))
        else:
            # 75th percentile: robust against lines made of short lowercase words
            self.h = float(np.percentile([w.h for w in self.words], 75))
        self.text = " ".join(w.text for w in self.words)
        # average glyph width: scales with font size but (unlike box height) not with ascenders/descenders
        self.cw = sum(w.x1 - w.x0 for w in self.words) / max(sum(len(w.text) for w in self.words), 1)
        self.bold = bool(self.words) and sum(1 for w in self.words if w.bold) / len(self.words) >= 0.9

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"Line({self.text[:40]!r}, y={self.cy:.0f}, h={self.h:.0f})"


def group_lines(words: List[Word], native: bool) -> List[Line]:
    """Cluster words into lines by vertical position, top to bottom."""
    if not words:
        return []
    ordered = sorted(words, key=lambda w: (w.cy, w.x0))
    groups, cur = [], [ordered[0]]
    cur_cy, cur_h = ordered[0].cy, ordered[0].h
    for w in ordered[1:]:
        if abs(w.cy - cur_cy) <= 0.5 * cur_h:
            cur.append(w)
            cur_cy = median(x.cy for x in cur)
            cur_h = median(x.h for x in cur)
        else:
            groups.append(cur)
            cur, cur_cy, cur_h = [w], w.cy, w.h
    groups.append(cur)
    return [Line(g, native) for g in groups]


def split_segments(line: Line, gap: float) -> List[List[Word]]:
    """Split a line into phrases wherever the horizontal whitespace exceeds `gap`."""
    segs, cur = [], [line.words[0]]
    for prev, w in zip(line.words, line.words[1:]):
        if w.x0 - prev.x1 > gap:
            segs.append(cur)
            cur = []
        cur.append(w)
    segs.append(cur)
    return segs


def seg_text(seg: List[Word]) -> str:
    return " ".join(w.text for w in seg)


def runs_of(mask: np.ndarray):
    """(start, end_exclusive) of every run of True in a 1-D boolean array."""
    out, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(mask)))
    return out
