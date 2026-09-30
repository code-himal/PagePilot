"""Plain data containers shared by the pipeline."""
from dataclasses import dataclass


@dataclass
class Word:
    """A single word with its bounding box in page coordinates.

    Coordinates are pixels for OCR pages and PDF points for native PDF pages;
    the layout engine only uses *relative* geometry, so both work.
    """
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float = 100.0      # OCR confidence 0-100 (native PDF text is always 100)
    size: float = 0.0        # font size (native PDFs only)
    bold: bool = False

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2.0

    @property
    def h(self) -> float:
        return max(self.y1 - self.y0, 0.01)

    @property
    def w(self) -> float:
        return max(self.x1 - self.x0, 0.01)
