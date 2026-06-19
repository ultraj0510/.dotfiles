"""Tests for STOCK REPORTS PDF parser."""
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdf_parser import parse_stock_report_pdf


@pytest.mark.skipif(importlib.util.find_spec("reportlab") is None,
                    reason="reportlab not installed")
def _make_minimal_pdf(path: Path):
    """Generate a minimal PDF with Japanese text for testing."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen.canvas import Canvas

    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    canvas = Canvas(str(path))
    canvas.setFont("HeiseiKakuGo-W5", 10)
    lines = [
        "更新日: 2026年6月15日",
        "企業概要: ゲーム開発・運営を主力とするIT企業",
        "売上高: 50,000百万円 (2026年3月期)",
        "営業利益: 12,500百万円 (2026年3月期)",
        "PER: 15.2倍",
        "PBR: 1.85倍",
        "業績変化: 新作ヒットにより上方修正",
        "リスク: 為替変動、競争激化",
    ]
    for index, line in enumerate(lines):
        canvas.drawString(40, 800 - index * 20, line)
    canvas.save()


def test_parse_stock_report_pdf_basic(tmp_path):
    if importlib.util.find_spec("reportlab") is None:
        pytest.skip("reportlab not installed")
    pdf_path = tmp_path / "test_report.pdf"
    _make_minimal_pdf(pdf_path)

    result = parse_stock_report_pdf(str(pdf_path))
    assert result["status"] == "ok"
    data = result["data"]
    assert "2026-06-15" in data.get("report_date", "")
    assert "ゲーム開発" in data.get("company_overview", "")
    assert "per" in data.get("key_metrics", {})
    assert "上方修正" in data.get("changes", "")
    assert "為替" in data.get("risk_factors", "")


def test_parse_stock_report_pdf_not_found():
    result = parse_stock_report_pdf("/nonexistent/path.pdf")
    assert result["status"] == "error"


def test_parse_stock_report_pdf_corrupted(tmp_path):
    pdf_path = tmp_path / "corrupted.pdf"
    pdf_path.write_text("not a real PDF file")
    result = parse_stock_report_pdf(str(pdf_path))
    assert result["status"] in ("error", "pdf_parse_failed")
