import pytest
from io import BytesIO

from document_extractor import extract_document, TesseractOcrEngine

# --- HTML extraction ---

HTML_BODY = b"<!doctype html><html><head><script>alert(1)</script><style>.x{}</style></head><body><nav>menu</nav><main><p>IR Library 2026</p></main></body></html>"


def test_extract_html_removes_script_style_nav():
    result = extract_document(HTML_BODY, "html")
    assert result["method"] == "html_text"
    assert "alert" not in result["text"]
    assert "menu" not in result["text"]
    assert "IR Library 2026" in result["text"]


# --- PDF text extraction (synthetic, ASCII-only) ---

def test_extract_pdf_text():
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(100, 700, "IR Financial Results FY2026 Q4")
    c.drawString(100, 680, "Revenue: 1,000 million yen")
    c.drawString(100, 660, "Operating Profit: 100 million yen")
    c.drawString(100, 640, "Net Income: 80 million yen")
    c.drawString(100, 620, "Tokyo, Japan - CEO Report Summary")
    c.drawString(100, 600, "Additional details and supplementary notes")
    c.showPage()
    c.save()
    body = buf.getvalue()
    assert body.startswith(b"%PDF")

    result = extract_document(body, "pdf")
    # With ASCII-only text and sufficient length, should use pdf_text
    assert result["method"] in ("pdf_text", "pdf_text_low_quality")
    assert "Financial Results" in result["text"]


# --- OCR engine ---

def test_ocr_engine_available_reports_status():
    engine = TesseractOcrEngine()
    available, msg = engine.available()
    assert isinstance(available, bool)
    assert isinstance(msg, str)


# --- Excel/CSV ---

def test_extract_xlsx_returns_not_applicable():
    result = extract_document(b"PK\x03\x04\x00\x00", "xlsx")
    assert result["method"] == "not_applicable"


def test_extract_csv_returns_not_applicable():
    result = extract_document(b"date,sales\n2026,100\n", "csv")
    assert result["method"] == "not_applicable"


def test_extract_unknown_returns_unsupported():
    result = extract_document(b"binary data", "exe")
    assert result["method"] == "unsupported"
