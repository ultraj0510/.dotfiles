"""Detect major IR/corporate events from document manifests."""
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

MAJOR_EVENT_PATTERNS = [
    (re.compile(r"業績予想.*(?:修正|上方修正|下方修正)"), "forecast_revision"),
    (re.compile(r"配当予想.*(?:修正|上方修正|下方修正)"), "dividend_revision"),
    (re.compile(r"決算短信"), "earnings_release"),
    (re.compile(r"決算説明"), "earnings_release"),
    (re.compile(r"自己株式.*(?:取得|消却)"), "share_buyback"),
    (re.compile(r"(?:増資|ライツオファリング|公募|売出)"), "capital_raising"),
    (re.compile(r"(?:合併|買収|M&A|TOB|株式交換|株式移転)"), "merger_acquisition"),
    (re.compile(r"代表取締役.*(?:異動|交代|選任|退任)"), "management_change"),
    (re.compile(r"主要株主.*(?:異動|変更)"), "shareholder_change"),
    (re.compile(r"(?:大型|重要).*契約"), "major_contract"),
    (re.compile(r"(?:訴訟|損害賠償|行政処分|行政指導|課徴金)"), "legal_regulatory"),
    (re.compile(r"(?:事故|災害|不具合|リコール|障害)"), "operational_incident"),
]


@dataclass
class Event:
    event_type: str
    ticker: str | None
    detected_at: str
    document_id: str
    title: str
    source: str = "stock-ir-fetch"
    summary: str = ""
    triggers_reanalysis: bool = True


def _classify_event(title, category):
    for pattern, event_type in MAJOR_EVENT_PATTERNS:
        if pattern.search(title):
            return event_type
    if category == "forecast_revision":
        return "forecast_revision"
    if category == "earnings_release":
        return "earnings_release"
    if category == "material_disclosure":
        return "material_disclosure"
    return None


def detect_events(prev_manifest, curr_manifest, info_result):
    events = []
    now = datetime.now(JST).isoformat()
    prev_ids = {d["document_id"] for d in prev_manifest.get("documents", [])} if prev_manifest else set()
    curr_docs = curr_manifest.get("documents", []) if curr_manifest else []

    for doc in curr_docs:
        doc_id = doc["document_id"]
        if doc_id in prev_ids:
            continue
        title = doc.get("title", "")
        event_type = _classify_event(title, doc.get("category", ""))
        if event_type:
            events.append(Event(
                event_type=event_type, ticker=None, detected_at=now,
                document_id=doc_id, title=title, summary=title,
            ))
    return events
