"""PDF parser for SBI STOCK REPORTS.

Uses pdfplumber for table and text extraction from Japanese financial PDFs.
Extracts structured facts only -- never stores full text or page images.
"""
import re
from datetime import datetime


def _normalize_cell(value: str) -> str:
    """Collapse whitespace and normalize separators."""
    return re.sub(r"\s+", " ", (value or "").replace("：", ":")).strip()


def _parse_number_and_unit(value: str, fallback_unit: str = "") -> tuple | None:
    """Parse a numeric value and optional unit from a cell.
    Longest units first to avoid partial matches (万株 before 株).
    Returns (float_value, unit_str) or None."""
    normalized = _normalize_cell(value)
    # Detect negative: ▲, △, or (123) format
    is_negative = bool(re.search(r"[▲△]", normalized)) or bool(re.match(r"\([\d,]+\)", normalized))
    cleaned = re.sub(r"[▲△()（）]", "", normalized)
    # Try with unit suffix (longer units first)
    for unit in ("百万円", "億円", "千円", "万株", "株", "円", "％", "%", "倍"):
        if unit in cleaned:
            num_part = cleaned.replace(unit, "").replace(",", "").strip()
            try:
                val = float(num_part)
                return -val if is_negative else val, "%" if unit == "％" else unit
            except ValueError:
                pass
    # Try plain number
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", cleaned)
    if match:
        try:
            val = float(match.group().replace(",", ""))
            return -val if is_negative else val, fallback_unit
        except ValueError:
            pass
    return None


def _parse_value_only(value: str) -> float | None:
    """Parse just a numeric value, ignoring unit text."""
    m = re.search(r"(-?[\d,]+\.?\d*)", _normalize_cell(value))
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


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
        tables_data = []  # list of tables, each table is list of rows
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"
            tables = page.extract_tables()
            for table in tables:
                normalized = [[c or "" for c in row] for row in table if row]
                if normalized:
                    tables_data.append(normalized)

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
    metrics = data.get("key_metrics", {})
    if isinstance(metrics, dict):
        for v in metrics.values():
            if isinstance(v, dict) and v.get("value") is not None:
                return True
    af = data.get("actual_and_forecast", {})
    for key in ("actual", "forecast"):
        for item in af.get(key, []):
            if isinstance(item, dict) and item.get("value") is not None:
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


def _extract_key_metrics(text: str, tables: list[list[list[str]]]) -> dict:
    metrics = {}

    TABLE_KEYS = {
        "per": ("per",), "pbr": ("pbr",), "eps": ("eps",), "bps": ("bps",),
        "roe": ("roe",), "roa": ("roa",),
    }
    for table in tables:
        for row in table:
            if len(row) < 2:
                continue
            label = _normalize_cell(row[0]).lower()
            for key, aliases in TABLE_KEYS.items():
                if any(a in label for a in aliases):
                    parsed = _parse_number_and_unit(row[1])
                    if parsed:
                        val, unit = parsed
                        if not unit and len(row) >= 3:
                            unit = _normalize_cell(row[2])
                            # Filter to known units only
                            if unit not in ("百万円", "億円", "千円", "万株", "株", "円", "%", "倍"):
                                unit = ""
                        metrics[key] = {"value": val, "unit": unit}
                    elif len(row) >= 3:
                        # Value and unit in separate cells
                        val = _parse_value_only(row[1])
                        if val is not None:
                            unit = _normalize_cell(row[2]) if len(row) >= 3 else ""
                            metrics[key] = {"value": val, "unit": unit}
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


def _extract_performance_data(text: str, tables: list[list[list[str]]]) -> dict:
    result = {"actual": [], "forecast": []}

    if not tables:
        return _extract_performance_text_fallback(text)

    KNOWN_METRICS = ("売上高", "営業利益", "経常利益", "当期純利益", "親会社株主に帰属する当期純利益")

    for table in tables:
        if len(table) < 2:
            continue
        # Build header model from this table only (first 5 rows max)
        period_row = [""] * 20
        kind_row = [""] * 20
        unit_row = [""] * 20
        data_start = 0
        for ri, row in enumerate(table[:5]):
            row = [_normalize_cell(c) for c in row]
            has_periods = any(re.match(r"\d{4}/\d{2}", c) for c in row)
            has_kinds = any(kw in c for c in row for kw in ("実績", "予想", "会社予想", "コンセンサス"))
            if has_periods:
                for ci, c in enumerate(row):
                    if ci < len(period_row):
                        period_row[ci] = c
                data_start = ri + 1
            elif has_kinds and not has_periods:
                for ci, c in enumerate(row):
                    if ci < len(kind_row):
                        kind_row[ci] = c
            elif ri > 0 and all(
                c in ("百万円", "億円", "千円", "円", "%", "倍", "株", "") or not c
                for c in row[1:] if c
            ):
                for ci, c in enumerate(row):
                    if ci < len(unit_row):
                        unit_row[ci] = c

        # Build column headers
        col_headers = {}
        for ci in range(1, min(20, max(len(r) for r in table))):
            period = ""
            kind = "actual"
            unit = ""
            if ci < len(period_row):
                m = re.search(r"(\d{4}/\d{2})", period_row[ci])
                if m:
                    period = m.group(1)
                if "実績" in period_row[ci]:
                    kind = "actual"
                elif "予想" in period_row[ci]:
                    kind = "forecast"
            if ci < len(kind_row):
                if "実績" in kind_row[ci]:
                    kind = "actual"
                elif "予想" in kind_row[ci]:
                    kind = "forecast"
            if ci < len(unit_row):
                for u in ("百万円", "億円", "千円", "円", "%", "倍"):
                    if u in unit_row[ci]:
                        unit = u
                        break
            if period:
                col_headers[ci] = {"period": period, "kind": kind, "unit": unit}

        # Parse data rows in this table
        for row in table[data_start:]:
            row = [_normalize_cell(c) for c in row]
            if not row or row[0] not in KNOWN_METRICS:
                continue
            metric = row[0]
            for ci, hdr in col_headers.items():
                if ci >= len(row):
                    continue
                parsed = _parse_number_and_unit(row[ci], hdr["unit"])
                if parsed:
                    val, unit = parsed
                    result[hdr["kind"]].append({
                        "metric": metric, "period": hdr["period"],
                        "value": val, "unit": unit or hdr["unit"],
                    })

    if not result["actual"] and not result["forecast"]:
        return _extract_performance_text_fallback(text)
    return result


def _extract_performance_text_fallback(text: str) -> dict:
    """Fallback text parser returning complete {metric, period, value, unit} schema."""
    result = {"actual": [], "forecast": []}
    # Pattern: 売上高 100,000百万円 → needs period from context
    for m in re.finditer(
        r"(売上高|営業利益|経常利益|当期純利益|親会社株主[に帰属する]*当期純利益)\s+([\d,]+)\s*([\d,]+)",
        text,
    ):
        metric = m.group(1)
        actual_val = float(m.group(2).replace(",", ""))
        forecast_val = float(m.group(3).replace(",", ""))
        if actual_val != 0:
            result["actual"].append({"metric": metric, "value": actual_val, "period": "", "unit": ""})
        if forecast_val != 0:
            result["forecast"].append({"metric": metric, "value": forecast_val, "period": "", "unit": ""})
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
