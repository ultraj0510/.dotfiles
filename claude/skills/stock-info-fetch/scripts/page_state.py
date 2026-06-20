"""SBI page state detection — login form, ticker-not-found, hidden element filtering."""
import re
from urllib.parse import urlparse as _urlparse

from bs4 import BeautifulSoup


def visible_soup(html: str):
    """Return BeautifulSoup with hidden/invisible elements removed."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(True):
        if tag.name in ("script", "style", "template"):
            tag.extract()
            continue
        if tag.get("hidden") is not None:
            tag.extract()
            continue
        style = re.sub(r"\s+", "", (tag.get("style") or "").lower())
        if "display:none" in style or "visibility:hidden" in style:
            tag.extract()
            continue
        aria = (tag.get("aria-hidden") or "").lower()
        if aria == "true":
            tag.extract()
            continue
    return soup


def _visible_text(html: str) -> str:
    """Extract visible text, excluding hidden elements."""
    return visible_soup(html).get_text(" ", strip=True)


def classify_page_state(html: str, url: str) -> str | None:
    """Classify the page state from HTML content and final URL.

    Returns:
        "auth_expired" — login form detected or redirected to login host.
        "ticker_not_found" — ticker-not-found marker visible on page.
        None — page appears normal.
    """
    # Check redirect host (not arbitrary URL substring).
    host = _urlparse(url).hostname
    if host and host.endswith("login.sbisec.co.jp"):
        return "auth_expired"
    # Check for login form structure (only in visible DOM, not hidden/template).
    if _has_login_form(html):
        return "auth_expired"
    visible = _visible_text(html)
    if "該当する銘柄はありません" in visible or "銘柄コードが正しくありません" in visible:
        return "ticker_not_found"
    return None


def _has_login_form(html: str) -> bool:
    """Check visible DOM for login form structure.

    Requires: form action containing 'login', OR a password input
    whose name does not suggest password-change (new/confirm/current/old),
    paired with a login-specific user-id field in the same form.
    Hidden/invisible elements are excluded via visible_soup.
    """
    soup = visible_soup(html)
    for form in soup.find_all("form"):
        # Find at least one non-change password input (not just the first).
        pw_inputs = form.find_all("input", type="password")
        has_login_pw = False
        for pw in pw_inputs:
            pw_name = (pw.get("name") or "").lower()
            pw_id = (pw.get("id") or "").lower()
            if not any(kw in pw_name or kw in pw_id
                       for kw in ("new", "confirm", "current", "old", "change")):
                has_login_pw = True
                break
        if not has_login_pw:
            continue

        # User-id field only counts if the action path is not a known non-login path.
        action = (form.get("action") or "").lower()
        action_path = _action_path(action)
        if action_path and any(kw in action_path for kw in (
            "change", "history", "help", "reset", "forgot", "register", "signup",
        )):
            continue

        for inp in form.find_all("input"):
            name = (inp.get("name") or "").lower()
            f_id = (inp.get("id") or "").lower()
            if name in ("userid", "user_id", "username", "login_id"):
                return True
            if f_id in ("userid", "user_id", "username", "login_id"):
                return True

        # Action path segments contain "login" as a complete component.
        if action_path and "login" in [s for s in action_path.split("/") if s]:
            return True
    return False


def _action_path(action: str) -> str:
    """Extract URL path from a form action, without query string."""
    return _urlparse(action).path
