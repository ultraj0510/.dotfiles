from datetime import datetime, time
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def classify_market_session(now: datetime | None = None) -> str:
    now = now or datetime.now(JST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=JST)
    now = now.astimezone(JST)
    if now.weekday() >= 5:
        return "closed"
    current = now.time()
    if current < time(9, 0):
        return "pre_open"
    if time(9, 0) <= current < time(11, 30):
        return "open"
    if time(11, 30) <= current < time(12, 30):
        return "lunch_break"
    if time(12, 30) <= current < time(15, 30):
        return "open"
    return "closed"


def is_price_stale(price_date: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(JST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=JST)
    today = now.astimezone(JST).date().isoformat()
    session = classify_market_session(now)
    if session == "open" and price_date != today:
        return {
            "is_stale": True,
            "reason": "previous_business_day_after_market_open",
            "market_session": session,
        }
    return {"is_stale": False, "reason": "", "market_session": session}
