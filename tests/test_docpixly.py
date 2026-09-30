"""Regression tests. Run with: pytest tests/ -q

Uses the fixture documents in samples/ (generate first with `python tests/make_samples.py samples`).
"""
import difflib
import io
import os
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SAMPLES = os.path.join(ROOT, "samples")

from pagepilot.numbers import parse_number
from pagepilot.pipeline import extract_document, parse_page_ranges, sniff_type
from pagepilot.textutil import clean_text, safe_filename
from pagepilot import exporters as ex
from pagepilot.errors import ExtractError


def sample(name):
    return os.path.join(SAMPLES, name)


def flat_words(res):
    out = []
    for pg in res["pages"]:
        for b in pg["blocks"]:
            if b["type"] == "table":
                for row in b["rows"]:
                    for c in row:
                        out += c.split()
            else:
                out += b["text"].split()
    return out


# ----------------------------------------------------------------------------- numbers.py
@pytest.mark.parametrize("text,expected", [
    ("1200", 1200), ("1,200.50", 1200.5), ("(1,200.00)", -1200), ("$1,200.00", 1200),
    ("007", None), ("9841234567", None), ("45%", None), ("12/03/2026", None),
    ("1,20", None), ("A-", None), ("", None), ("3.14", 3.14),
])
def test_parse_number(text, expected):
    r = parse_number(text)
    got = None if r is None else r[0]
    assert got == expected


def test_parse_number_long_ids_stay_text():
    assert parse_number("123456789012") is None       # 12-digit account number
    assert parse_number("1,234,567,890") == (1234567890, "#,##0")  # but a real big total is fine


# ----------------------------------------------------------------------------- textutil.py
def test_clean_text_strips_illegal_xml_chars():
    assert clean_text("a\x00b\x0bc") == "abc"


def test_safe_filename():
    assert safe_filename("../../etc/passwd?.pdf") == "passwd"
    assert safe_filename("") == "document"
    assert safe_filename("मार्कसिट.pdf") == "मार्कसिट"


# ----------------------------------------------------------------------------- pipeline plumbing
def test_sniff_type(tmp_path):
    pdf = tmp_path / "a.pdf"; pdf.write_bytes(b"%PDF-1.4\n...")
    png = tmp_path / "a.png"; png.write_bytes(b"\x89PNG\r\n\x1a\n...")
    txt = tmp_path / "a.txt"; txt.write_bytes(b"hello")
    assert sniff_type(str(pdf)) == "pdf"
    assert sniff_type(str(png)) == "image"
    assert sniff_type(str(txt)) is None


def test_parse_page_ranges():
    assert parse_page_ranges("1-3,5", 10) == [0, 1, 2, 4]
    assert parse_page_ranges("8-", 10) == [7, 8, 9]
    assert parse_page_ranges("", 5) == [0, 1, 2, 3, 4]
    with pytest.raises(ExtractError):
        parse_page_ranges("abc", 5)
    with pytest.raises(ExtractError):
        parse_page_ranges("99", 5)


# ----------------------------------------------------------------------------- digital PDFs (exact content)
def test_marksheet_digital():
    r = extract_document(sample("marksheet_digital.pdf"), "m.pdf")
    fields = {f["key"]: f["value"] for f in r["fields"]}
    assert fields["Name"] == "Himal Shrestha"
    assert fields["Program"] == "BSc IT"
    tables = [b for b in r["pages"][0]["blocks"] if b["type"] == "table"]
    assert len(tables) == 1
    assert tables[0]["rows"][0] == ["Subject", "Grade", "Credit"]
    assert ["Programming", "A", "3"] in tables[0]["rows"]
    headings = [b for b in r["pages"][0]["blocks"] if b["type"] == "heading"]
    assert headings[0]["text"] == "Himalaya College of Technology"
    assert headings[0]["level"] == 1


def test_invoice_digital():
    r = extract_document(sample("invoice_digital.pdf"), "i.pdf")
    fields = {f["key"]: f["value"] for f in r["fields"]}
    assert fields["Invoice number"] == "INV-2026-0042"
    tables = [b for b in r["pages"][0]["blocks"] if b["type"] == "table"]
    assert ["Laptop stand", "2", "$1,200.50", "$2,401.00"] in tables[0]["rows"]


def test_attendance_digital_borderless_table():
    r = extract_document(sample("attendance_digital.pdf"), "a.pdf")
    tables = [b for b in r["pages"][0]["blocks"] if b["type"] == "table"]
    assert len(tables) == 1
    assert tables[0]["rows"][0] == ["Name", "Mon", "Tue", "Wed", "Thu", "Fri"]
    assert ["Anita Gurung", "P", "P", "A", "P", "P"] in tables[0]["rows"]


def test_report_digital_headings_and_bullets():
    r = extract_document(sample("report_digital.pdf"), "r.pdf")
    blocks = r["pages"][0]["blocks"]
    kinds = [b["type"] for b in blocks]
    assert "heading" in kinds and "list_item" in kinds
    bullets = [b["text"] for b in blocks if b["type"] == "list_item"]
    assert "Increase laboratory hours" in bullets


def test_two_column_reading_order():
    r = extract_document(sample("two_column_digital.pdf"), "t.pdf")
    texts = " ".join(b["text"] for b in r["pages"][0]["blocks"] if b["type"] == "paragraph")
    assert texts.index("LEFTSTART") < texts.index("RIGHTSTART")


# ----------------------------------------------------------------------------- scanned / OCR path
@pytest.mark.parametrize("scan,digital", [
    ("marksheet_scan.jpg", "marksheet_digital.pdf"),
    ("invoice_scan.jpg", "invoice_digital.pdf"),
    ("attendance_scan.png", "attendance_digital.pdf"),
    ("report_scan.png", "report_digital.pdf"),
    ("invoice_rotated90.png", "invoice_digital.pdf"),
])
def test_scan_matches_digital_ground_truth(scan, digital):
    got = extract_document(sample(scan), scan)
    truth = extract_document(sample(digital), digital)
    sim = difflib.SequenceMatcher(None, flat_words(truth), flat_words(got), autojunk=False).ratio()
    assert sim > 0.9, f"{scan}: word similarity only {sim:.2f}"


def test_scanned_pdf_no_text_layer():
    r = extract_document(sample("marksheet_scanned.pdf"), "s.pdf")
    assert r["pages"][0]["method"] == "ocr"
    assert r["stats"]["tables"] == 1


def test_page_range_selection():
    r = extract_document(sample("marksheet_digital.pdf"), "m.pdf", pages_spec="1")
    assert len(r["pages"]) == 1
    with pytest.raises(ExtractError):
        extract_document(sample("marksheet_digital.pdf"), "m.pdf", pages_spec="5")


# ----------------------------------------------------------------------------- exporters.py
def _clean(res):
    for pg in res["pages"]:
        pg.pop("preview", None)
    return res


def test_export_docx_txt_xlsx_csv_roundtrip():
    r = _clean(extract_document(sample("marksheet_digital.pdf"), "Marksheet.pdf"))
    for fmt in ("docx", "txt", "xlsx", "csv"):
        data, name, mime = ex.export([r], fmt)
        assert data and name.endswith("." + fmt)


def test_export_xlsx_without_tables_errors():
    r = _clean(extract_document(sample("report_digital.pdf"), "r.pdf"))
    with pytest.raises(ExtractError):
        ex.export([r], "xlsx")


def test_export_batch_zips():
    a = _clean(extract_document(sample("marksheet_digital.pdf"), "a.pdf"))
    b = _clean(extract_document(sample("invoice_digital.pdf"), "b.pdf"))
    data, name, mime = ex.export([a, b], "xlsx")
    assert name.endswith(".zip")
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert len(names) == 2


def test_export_rejects_oversized_and_malformed_input():
    with pytest.raises(ExtractError):
        ex.export([{"pages": "not-a-list"}], "docx")
    with pytest.raises(ExtractError):
        ex.export([], "docx")
    with pytest.raises(ExtractError):
        ex.export([{"pages": []}], "pptx")   # unsupported format


def test_csv_injection_is_neutralised():
    doc = {"filename": "x", "pages": [{"number": 1, "blocks": [
        {"type": "table", "header": True, "rows": [["A", "B"], ["=1+1", "normal"]]}
    ]}], "fields": []}
    data, name, mime = ex.export([doc], "csv")
    text = data.decode("utf-8-sig")
    assert "'=1+1" in text        # neutralised, not executed as a formula by spreadsheet apps


def test_docx_edits_round_trip():
    """A hand-edited cell (as the browser would send) must appear in the exported file."""
    from docx import Document
    doc = {"filename": "x", "pages": [{"number": 1, "blocks": [
        {"type": "table", "header": True, "rows": [["Subject", "Grade"], ["Programming", "A+"]]}
    ]}], "fields": []}
    data, name, mime = ex.export([doc], "docx")
    d = Document(io.BytesIO(data))
    cells = [c.text for row in d.tables[0].rows for c in row.cells]
    assert "A+" in cells
