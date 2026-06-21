"""Extract text from PDF and HTML documents with OCR fallback."""
import io

from bs4 import BeautifulSoup


def extract_document(body, extension, now=None, ocr_engine=None):
    """Extract text from a document. Returns ExtractionResult dict."""
    if extension == "pdf":
        return _extract_pdf(body, ocr_engine)
    elif extension == "html":
        return _extract_html(body)
    elif extension in ("xlsx", "xls", "csv"):
        return {
            "method": "not_applicable",
            "text": "",
            "page_count": None,
            "quality_warnings": [],
            "error": None,
        }
    return {
        "method": "unsupported",
        "text": "",
        "page_count": None,
        "quality_warnings": [],
        "error": {"code": "unsupported_format", "message": f"No extractor for {extension}"},
    }


def _extract_pdf(body, ocr_engine):
    import pdfplumber
    try:
        with pdfplumber.open(io.BytesIO(body)) as pdf:
            page_count = len(pdf.pages)
            if page_count > 300:
                return {
                    "method": "pdf_rejected",
                    "text": "",
                    "page_count": page_count,
                    "quality_warnings": ["page_limit_exceeded"],
                    "error": {"code": "page_limit_exceeded", "message": f"PDF has {page_count} pages (max 300)"},
                }
            text_parts = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                text_parts.append(t)
            text = "\n".join(text_parts)
    except Exception as e:
        return {
            "method": "pdf_error",
            "text": "",
            "page_count": None,
            "quality_warnings": [],
            "error": {"code": "pdf_parse_error", "message": str(e)[:200]},
        }

    readable = sum(1 for c in text if c.isalnum() or "぀" <= c <= "ヿ" or "一" <= c <= "鿿")
    ratio = readable / max(len(text), 1)
    if len(text.strip()) >= 200 and ratio >= 0.60:
        return {
            "method": "pdf_text",
            "text": text,
            "page_count": page_count,
            "quality_warnings": [],
            "error": None,
        }

    # OCR fallback
    if ocr_engine:
        available, msg = ocr_engine.available()
        if available:
            try:
                ocr_text, ocr_pages = ocr_engine.extract_pdf(body, max_pages=50)
                return {
                    "method": "ocr",
                    "text": ocr_text,
                    "page_count": ocr_pages,
                    "quality_warnings": ["ocr_used"],
                    "error": None,
                }
            except Exception as e:
                return {
                    "method": "ocr_failed",
                    "text": text,
                    "page_count": page_count,
                    "quality_warnings": ["ocr_error"],
                    "error": {"code": "ocr_error", "message": str(e)[:200]},
                }
        else:
            return {
                "method": "ocr_unavailable",
                "text": text,
                "page_count": page_count,
                "quality_warnings": ["ocr_unavailable", msg],
                "error": None,
            }

    return {
        "method": "pdf_text_low_quality",
        "text": text,
        "page_count": page_count,
        "quality_warnings": ["low_readability"],
        "error": None,
    }


def _extract_html(body):
    try:
        soup = BeautifulSoup(body, "html.parser")
    except Exception:
        return {
            "method": "html_error",
            "text": "",
            "page_count": None,
            "quality_warnings": [],
            "error": {"code": "html_parse_error", "message": "Failed to parse HTML"},
        }
    for tag in soup.find_all(["script", "style", "nav", "form", "noscript"]):
        tag.decompose()
    for tag in soup.find_all(attrs={"hidden": True}):
        tag.decompose()
    for tag in soup.find_all(attrs={"aria-hidden": "true"}):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    # Normalize whitespace
    import re
    text = re.sub(r"\s+", " ", text).strip()
    return {
        "method": "html_text",
        "text": text,
        "page_count": None,
        "quality_warnings": [],
        "error": None,
    }


class TesseractOcrEngine:
    def available(self):
        try:
            import pytesseract
            languages = set(pytesseract.get_languages(config=""))
            if {"jpn", "eng"}.issubset(languages):
                return True, "jpn+eng available"
            return False, f"Missing language data: have {sorted(languages)}"
        except Exception as e:
            return False, f"Tesseract unavailable: {e}"

    def extract_pdf(self, body, max_pages=50):
        import pypdfium2 as pdfium
        import pytesseract
        from PIL import Image

        pdf = pdfium.PdfDocument(body)
        page_count = len(pdf)
        if page_count > max_pages:
            raise ValueError(f"PDF has {page_count} pages (OCR max {max_pages})")

        text_parts = []
        for i in range(min(page_count, max_pages)):
            page = pdf[i]
            bitmap = page.render(scale=150 / 72)
            pil_image = Image.fromarray(bitmap.to_numpy())
            page_text = pytesseract.image_to_string(pil_image, lang="jpn+eng")
            text_parts.append(page_text)

        return "\n".join(text_parts), page_count
