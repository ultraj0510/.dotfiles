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

        if not full_text.strip() and not tables_data:
            return {"status": "error", "data": {}, "error_code": "pdf_parse_failed",
                    "message": "No extractable text or tables in PDF"}

        data = {
            "report_date": _extract_report_date(full_text),
            "company_overview": _extract_company_overview(full_text),
            "key_metrics": _extract_key_metrics(full_text, tables_data),
            "actual_and_forecast": _extract_performance_data(full_text, tables_data),
            "changes": _extract_changes(full_text),
            "risk_factors": _extract_risk_factors(full_text),
        }
        if not _has_minimum_data(data):
            return {"status": "source_changed", "data": data}
        return {"status": "ok", "data": data}
    except Exception as e:
        return {"status": "error", "data": {}, "error_code": "pdf_parse_failed",
                "message": str(e)[:200]}
    finally:
        try:
            pdf.close()
        except Exception:
            pass


def _has_minimum_data(data: dict) -> bool:
    if not data["report_date"]:
        return False
    metrics = data["key_metrics"]
    if isinstance(metrics, dict) and any(
        isinstance(v, dict) and v.get("value") is not None for v in metrics.values()
    ):
        return True
    af = data["actual_and_forecast"]
    for key in ("actual", "forecast"):
        if af.get(key) and any(item.get("value") is not None for item in af[key]):
            return True
    return False


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

    # Primary: extract from table rows with value and unit
    TABLE_KEYS = {
        "per": ("per",), "pbr": ("pbr",), "eps": ("eps",), "bps": ("bps",),
        "roe": ("roe",), "roa": ("roa",),
    }
    for row in tables:
        if len(row) < 2:
            continue
        label = row[0].strip().lower()
        for key, aliases in TABLE_KEYS.items():
            if any(a in label for a in aliases):
                try:
                    val = float(row[1].replace(",", "").replace("倍", "").replace("円", "").replace("%", "").replace(" ", ""))
                    unit = row[2].strip() if len(row) >= 3 else ""
                    metrics[key] = {"value": val, "unit": unit}
                except (ValueError, IndexError):
                    pass
                break

    # Fall back to text patterns if tables yielded < 2 metrics
    if len(metrics) < 2:
        metric_patterns = [
            (r"PER[：:]?\s*([\d,.]+)\s*(倍)?", "per", "倍"),
            (r"PBR[：:]?\s*([\d,.]+)\s*(倍)?", "pbr", "倍"),
            (r"EPS[：:]?\s*([\d,.]+)\s*(円)?", "eps", "円"),
            (r"BPS[：:]?\s*([\d,.]+)\s*(円)?", "bps", "円"),
            (r"ROE[：:]?\s*([\d,.]+)\s*%", "roe", "%"),
            (r"ROA[：:]?\s*([\d,.]+)\s*%", "roa", "%"),
        ]
        for pattern, key, default_unit in metric_patterns:
            m = re.search(pattern, text)
            if m:
                try:
                    groups = m.groups()
                    unit = groups[1].strip() if len(groups) >= 2 and groups[1] else default_unit
                    metrics[key] = {"value": float(m.group(1).replace(",", "")), "unit": unit}
                except ValueError:
                    pass
    return metrics


def _extract_performance_data(text: str, tables: list[list[str]]) -> dict:
    result = {"actual": [], "forecast": []}

    # Try table-based extraction first: find header row with fiscal periods
    period_pattern = re.compile(r"(\d{4}/\d{2})")
    header_periods = None
    for row in tables:
        row_periods = []
        for ci, cell in enumerate(row):
            pm = period_pattern.search(cell)
            if pm:
                af = "actual" if "実績" in cell else "forecast"
                row_periods.append((ci, pm.group(1), af))
        if row_periods:
            header_periods = row_periods
            break

    METRIC_NAMES = ("売上高", "営業利益", "経常利益", "当期純利益", "親会社株主に帰属する当期純利益")
    if header_periods:
        for row in tables:
            metric_name = row[0].strip()
            if metric_name not in METRIC_NAMES:
                continue
            for ci, period, af in header_periods:
                if ci < len(row):
                    try:
                        val_str = row[ci].replace(",", "").replace("百万円", "").replace("億円", "").strip()
                        val = float(val_str)
                        unit = _extract_unit(row[-1]) if len(row) > ci + 1 else ""
                        result[af].append({
                            "metric": metric_name,
                            "period": period,
                            "value": val,
                            "unit": unit,
                        })
                    except (ValueError, IndexError):
                        pass

    # Fall back to text regex if tables didn't yield results
    if not result["actual"] and not result["forecast"]:
        for m in re.finditer(
            r"(売上高|営業利益|経常利益|当期純利益|親会社株主[に帰属する]*当期純利益)\s+([\d,]+)\s+([\d,]+)",
            text,
        ):
            result["actual"].append({"metric": m.group(1), "value": float(m.group(2).replace(",", ""))})
            result["forecast"].append({"metric": m.group(1), "value": float(m.group(3).replace(",", ""))})

    return result


def _extract_unit(cell: str) -> str:
    """Extract unit from a cell like '百万円' or '億円'."""
    for unit in ("百万円", "億円", "千円", "円", "%", "倍", "株", "万株"):
        if unit in cell:
            return unit
    return ""


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
