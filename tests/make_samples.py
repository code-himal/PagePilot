"""Generate sample documents with known content (used by the tests and shipped as demo files)."""
import io
import os
import sys

import cv2
import numpy as np
import pypdfium2 as pdfium
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle, PageBreak, FrameBreak, BaseDocTemplate, Frame, PageTemplate,
                                NextPageTemplate)

ss = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=ss["Normal"], fontName="Helvetica", fontSize=11, leading=15)
H1 = ParagraphStyle("h1", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=22, leading=28, spaceAfter=8)
H2 = ParagraphStyle("h2", parent=ss["Normal"], fontName="Helvetica-Bold", fontSize=15, leading=20, spaceBefore=10, spaceAfter=4)

MARKS = [["Subject", "Grade", "Credit"], ["Programming", "A", "3"], ["Database", "A-", "3"],
         ["Networking", "B+", "3"], ["Mathematics", "B", "4"], ["English", "A", "2"]]
INVOICE = [["Item", "Qty", "Unit Price", "Amount"], ["Laptop stand", "2", "$1,200.50", "$2,401.00"],
           ["USB-C hub", "5", "$45.00", "$225.00"], ["Wireless mouse", "10", "$18.75", "$187.50"],
           ["HDMI cable", "4", "$9.99", "$39.96"]]
ATTEND = [["Name", "Mon", "Tue", "Wed", "Thu", "Fri"], ["Anita Gurung", "P", "P", "A", "P", "P"],
          ["Bikash Rai", "P", "A", "P", "P", "P"], ["Chandra Thapa", "A", "P", "P", "P", "A"],
          ["Deepa Karki", "P", "P", "P", "P", "P"], ["Eshan Lama", "P", "P", "A", "A", "P"]]

LOREM = ("The committee reviewed the annual performance of the department and concluded that student "
         "enrolment has grown steadily over the last three years. Laboratory facilities were upgraded and "
         "several new courses were introduced to meet industry demand. ")


def grid_table(data, widths, ruled=True, align_right_from=None):
    t = Table(data, colWidths=widths)
    style = [("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 10.5),
             ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("TOPPADDING", (0, 0), (-1, -1), 6),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]
    if ruled:
        style += [("GRID", (0, 0), (-1, -1), 0.8, colors.black), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8E8E8"))]
    if align_right_from is not None:
        style.append(("ALIGN", (align_right_from, 0), (-1, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    return t


def build(path, story):
    SimpleDocTemplate(path, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                      topMargin=20 * mm, bottomMargin=20 * mm).build(story)


def make_marksheet(path):
    build(path, [Paragraph("Himalaya College of Technology", H1), Paragraph("Semester Grade Sheet", H2),
                 Spacer(1, 6), Paragraph("Name: Himal Shrestha", BODY), Paragraph("Program: BSc IT", BODY),
                 Paragraph("Roll No: 2078-101", BODY), Spacer(1, 12),
                 grid_table(MARKS, [80 * mm, 30 * mm, 30 * mm]), Spacer(1, 14),
                 Paragraph("This grade sheet is computer generated and valid without a signature.", BODY)])


def make_invoice(path):
    build(path, [Paragraph("Invoice", H1), Paragraph("Invoice number: INV-2026-0042", BODY),
                 Paragraph("Date: 2026-09-01", BODY), Spacer(1, 12),
                 grid_table(INVOICE, [70 * mm, 20 * mm, 35 * mm, 35 * mm], align_right_from=1), Spacer(1, 12),
                 Paragraph("Payment is due within 30 days of the invoice date. Thank you for your business.", BODY)])


def make_attendance(path):
    build(path, [Paragraph("Weekly Attendance", H1), Paragraph("Class 10-B, week of 14 September", BODY),
                 Spacer(1, 10), grid_table(ATTEND, [50 * mm, 20 * mm, 20 * mm, 20 * mm, 20 * mm, 20 * mm], ruled=False),
                 Spacer(1, 12), Paragraph("P = present, A = absent.", BODY)])


def make_report(path):
    bullets = ListFlowable([ListItem(Paragraph(t, BODY)) for t in
                            ["Increase laboratory hours", "Hire two additional lecturers", "Upgrade the network"]],
                           bulletType="bullet", start="•")
    build(path, [Paragraph("Annual Department Report", H1), Paragraph("1. Overview", H2),
                 Paragraph(LOREM * 2, BODY), Paragraph(LOREM, BODY), Paragraph("2. Recommendations", H2),
                 Paragraph("The committee makes the following recommendations for the coming year.", BODY),
                 bullets, Spacer(1, 8), Paragraph("3. Conclusion", H2), Paragraph(LOREM * 2, BODY)])


def make_two_column(path):
    doc = BaseDocTemplate(path, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=20 * mm, bottomMargin=20 * mm)
    w, h = A4
    gap = 10 * mm
    cw = (w - 40 * mm - gap) / 2
    frames = [Frame(20 * mm, 20 * mm, cw, h - 40 * mm - 30 * mm, id="l"),
              Frame(20 * mm + cw + gap, 20 * mm, cw, h - 40 * mm - 30 * mm, id="r")]
    title = Frame(20 * mm, h - 20 * mm - 30 * mm, w - 40 * mm, 30 * mm, id="t")
    doc.addPageTemplates([PageTemplate(id="two", frames=[title] + frames)])
    story = [Paragraph("Two Column Article", H1), FrameBreak(),
             Paragraph("LEFTSTART " + LOREM * 3, BODY), Paragraph(LOREM * 2, BODY), FrameBreak(),
             Paragraph("RIGHTSTART " + LOREM * 3, BODY), Paragraph(LOREM * 2, BODY)]
    doc.build(story)


def rasterize(pdf_path, dpi=200):
    pdf = pdfium.PdfDocument(pdf_path)
    imgs = [pdf[i].render(scale=dpi / 72.0).to_pil().convert("L") for i in range(len(pdf))]
    pdf.close()
    return imgs


def degrade(pil, angle=1.6, noise=10, blur=0.8, seed=1):
    """Make a clean render look like a real scan: skew, grey background, noise, blur."""
    rng = np.random.default_rng(seed)
    a = np.array(pil).astype(np.float32)
    h, w = a.shape
    a = a * 0.93 + 8                                         # slightly grey paper
    yy, xx = np.mgrid[0:h, 0:w]
    a *= (0.93 + 0.07 * (xx / w))                            # gentle lighting gradient
    a += rng.normal(0, noise, a.shape)
    a = np.clip(a, 0, 255).astype(np.uint8)
    if blur:
        a = cv2.GaussianBlur(a, (0, 0), blur)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    a = cv2.warpAffine(a, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=235)
    return Image.fromarray(a)


def main(out):
    os.makedirs(out, exist_ok=True)
    pdfs = {"marksheet": make_marksheet, "invoice": make_invoice, "attendance": make_attendance,
            "report": make_report, "two_column": make_two_column}
    for name, fn in pdfs.items():
        fn(os.path.join(out, f"{name}_digital.pdf"))
    # scanned variants
    for name, angle in (("marksheet", 1.6), ("invoice", -1.1), ("attendance", 0.9), ("report", 0.6)):
        img = degrade(rasterize(os.path.join(out, f"{name}_digital.pdf"))[0], angle=angle)
        ext = "jpg" if name in ("marksheet", "invoice") else "png"
        img.save(os.path.join(out, f"{name}_scan.{ext}"), quality=82) if ext == "jpg" else img.save(os.path.join(out, f"{name}_scan.{ext}"))
    # scanned PDF (image only, no text layer)
    img = degrade(rasterize(os.path.join(out, "marksheet_digital.pdf"))[0], angle=-0.8, seed=5).convert("L")
    img.save(os.path.join(out, "marksheet_scanned.pdf"), "PDF", resolution=200)
    # rotated 90 degrees (phone held sideways)
    img = degrade(rasterize(os.path.join(out, "invoice_digital.pdf"))[0], angle=0.5, seed=3)
    img.rotate(-90, expand=True).save(os.path.join(out, "invoice_rotated90.png"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "samples"))
