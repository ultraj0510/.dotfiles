"""PDF parser for SBI STOCK REPORTS.

Uses pdfplumber for table and text extraction from Japanese financial PDFs.
Extracts structured facts only -- never stores full text or page images.
"""
import re
from datetime import datetime


def parse_stock_report_pdf(pdf_path: str) -> dict:
    """Parse a STOCK REPORTS PDF into structured investment facts.

    Returns:
        {"status": "ok|error|pdf_parse_failed", "data": {...}}

    Data keys:
        report_date: ISO date string
        company_overview: short text
        key_metrics: dict of metric_name -> value
        actual_and_forecast: dict with "actual" and "forecast" lists
        changes: text describing notable changes
        risk_factors: text listing identified risks
    """
    try:
        import pdfplumber
    except ImportError:
        return {"status": "error", "data": {}, "error_code": "pdf_parse_failed",
                "message": "pdfplumber not installed"}

    try:
        pdf = pdfplumber.open(pdf_path)
    except Exception:
        return {"status": "error", "data": {}, "error_code": "pdf_unavailable",
                "message": "Cannot open PDF file"}

    try:
        full_text = ""
        tables_data = []
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row:
                        tables_data.append([c or "" for c in row])

        if not full_text.strip():
            return {"status": "error", "data": {}, "error_code": "pdf_parse_failed",
                    "message": "No extractable text in PDF"}

        data = {
            "report_date": _extract_report_date(full_text),
            "company_overview": _extract_company_overview(full_text),
            "key_metrics": _extract_key_metrics(full_text, tables_data),
            "actual_and_forecast": _extract_performance_data(full_text, tables_data),
            "changes": _extract_changes(full_text),
            "risk_factors": _extract_risk_factors(full_text),
        }
        return {"status": "ok", "data": data}
    except Exception as e:
        return {"status": "error", "data": {}, "error_code": "pdf_parse_failed",
                "message": str(e)[:200]}
    finally:
        try:
            pdf.close()
        except Exception:
            pass


def _extract_report_date(text: str) -> str:
    m = re.search(r"更新日[：:]?\s*(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(\d{4}/\d{1,2}/\d{1,2})", text)
    if m:
        try:
            dt = datetime.strptime(m.group(1), "%Y/%m/%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def _extract_company_overview(text: str) -> str:
    m = re.search(r"企業概要[：:]?\s*(.+?)(?:\n\n|\n[^\s]*[：:]|\Z)", text, re.DOTALL)
    if m:
        return m.group(1).strip()[:500]
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if "企業概要" in line and i + 1 < len(lines):
            return lines[i + 1].strip()[:500]
    return ""


def _extract_key_metrics(text: str, tables: list[list[str]]) -> dict:
    metrics = {}
    metric_patterns = [
        (r"PER[：:]?\s*([\d,.]+)\s*倍", "per"),
        (r"PBR[：:]?\s*([\d,.]+)\s*倍", "pbr"),
        (r"EPS[：:]?\s*([\d,.]+)\s*円", "eps"),
        (r"BPS[：:]?\s*([\d,.]+)\s*円", "bps"),
        (r"ROE[：:]?\s*([\d,.]+)\s*%", "roe"),
        (r"ROA[：:]?\s*([\d,.]+)\s*%", "roa"),
        (r"自己資本比率[：:]?\s*([\d,.]+)\s*%", "equity_ratio"),
        (r"配当利回り[：:]?\s*([\d,.]+)\s*%", "dividend_yield"),
        (r"時価総額[：:]?\s*([\d,.]+)\s*億円", "market_cap_billion_yen"),
        (r"発行済株式数[：:]?\s*([\d,.]+)\s*万株", "shares_outstanding_10k"),
    ]
    for pattern, key in metric_patterns:
        m = re.search(pattern, text)
        if m:
            try:
                metrics[key] = float(m.group(1).replace(",", ""))
            except ValueError:
                metrics[key] = m.group(1)
    return metrics


def _extract_performance_data(text: str, tables: list[list[str]]) -> dict:
    result = {"actual": [], "forecast": []}
    for m in re.finditer(r"(売上高|営業利益|経常利益|当期純利益|親会社株主[に帰属する]*当期純利益)\s+([\d,]+)\s+([\d,]+)", text):
        metric = m.group(1)
        actual_val = float(m.group(2).replace(",", ""))
        forecast_val = float(m.group(3).replace(",", ""))
        result["actual"].append({"metric": metric, "value": actual_val})
        result["forecast"].append({"metric": metric, "value": forecast_val})
    return result


def _extract_changes(text: str) -> str:
    m = re.search(r"(業績[のの]?変化|業績変化|評価[のの]?変化)[：:]?\s*(.+?)(?:\n\n|\n[^\s]*[：:]|\Z)", text, re.DOTALL)
    if m:
        return m.group(2).strip()[:500]
    return ""


def _extract_risk_factors(text: str) -> str:
    m = re.search(r"(リスク[要因因子]*|注意事項|留意事項)[：:]?\s*(.+?)(?:\n\n|\n[^\s]*[：:]|\Z)", text, re.DOTALL)
    if m:
        return m.group(2).strip()[:1000]
    return ""
