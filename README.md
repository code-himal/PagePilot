# DocPixly

Turn a PDF, photo or scan into an editable Word, Excel, CSV or text file.

```
PDF / JPG / PNG ─▶ read text (OCR or native PDF text) ─▶ find tables
                                                         ─▶ review & edit in the browser
                                                         ─▶ download .docx / .xlsx / .csv / .txt
```

## What it does

- **Reads native PDFs directly** (no OCR needed) and falls back to OCR per-page for
  scanned PDFs, photos and image-only pages — decided automatically per page.
- **Finds tables two ways**: ruled grids (detected from grid lines with OpenCV /
  pdfplumber) and borderless tables (detected from column whitespace — attendance
  sheets, many invoices).
- **Rebuilds reading order**: headings, paragraphs, bullet lists, and two-column
  layouts, plus "Key: value" field pairs (Name, Invoice number, Date, ...).
- **Deskews, corrects orientation and normalises lighting** before OCR, and retries a
  second Tesseract page mode automatically when the first pass looks unsure.
- **Lets you review and fix text before downloading** — every block and table cell is
  editable in the browser; low-confidence cells are flagged.
- **Batch**: upload several files at once, download them individually or all together
  as a zip.
- Ships with English and Nepali OCR out of the box (any Tesseract language pack you
  install becomes available automatically).

## Running it

```bash
pip install -r requirements.txt --break-system-packages   # or use a virtualenv
python app.py                                              # http://127.0.0.1:5000
```

Requires the `tesseract-ocr` and `poppler-utils` system packages (for `pdftoppm`);
on Debian/Ubuntu:

```bash
apt-get install tesseract-ocr tesseract-ocr-nep poppler-utils
```

For production, run behind a real WSGI server, e.g.:

```bash
gunicorn -w 2 --threads 4 -b 0.0.0.0:8000 'app:app'
```

Each worker OCRs one file at a time by design (`Config.MAX_CONCURRENT`); add more
worker processes to raise throughput, not more threads per worker — Tesseract
is CPU-bound.

## Configuration

Everything in `docpixly/config.py` is overridable with an environment variable, e.g.:

```bash
DOCPIXLY_MAX_UPLOAD_MB=40 DOCPIXLY_MAX_PAGES=50 python app.py
```

## Project layout

```
app.py                  entry point (dev server / gunicorn target)
docpixly/
  config.py              all tunables
  pipeline.py             orchestrates one file -> JSON result
  imaging.py              deskew, orientation, lighting, grid-line detection (OpenCV)
  ocr.py                  Tesseract wrapper (language list, page OCR, cell OCR, OSD rotation)
  tables.py                ruled-grid + borderless table detectors
  layout.py                 reading order: columns, paragraphs, headings, lists, fields
  geometry.py                word -> line -> segment grouping shared by tables & layout
  numbers.py                  conservative text -> Excel-number parser
  exporters.py                DOCX / XLSX / CSV / TXT generation + input validation
  web.py                       Flask app (routes, error handling, security headers)
templates/, static/           the browser UI (vanilla HTML/CSS/JS, no build step)
tests/                        pytest suite + synthetic sample-document generator
samples/                      generated sample PDFs/images used by the tests
```

## Testing

```bash
python tests/make_samples.py samples   # (re)generate the fixture documents
pytest tests/ -q
```

The fixtures include both clean "digital" PDFs and deliberately degraded versions
(skewed, noisy, uneven lighting, rotated, image-only) so the test suite exercises the
real OCR path, not just the native-PDF path.

## Roadmap (not built yet)

- Structured invoice/receipt field extraction + JSON export
- Page-thumbnail drag-to-reorder before export
- Per-account usage limits / auth, if this moves beyond a single-server demo
