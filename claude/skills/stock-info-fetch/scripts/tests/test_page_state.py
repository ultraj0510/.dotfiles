"""Tests for SBI page state detection."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from page_state import classify_page_state, visible_soup


@pytest.mark.parametrize(("html", "url", "expected"), [
    ("<form action='/login'><input name='userid'><input type='password'></form>",
     "https://site1.sbisec.co.jp/ETGate/", "auth_expired"),
    ("<form action='/change-password'><input name='userid'><input type='password'></form>",
     "https://site1.sbisec.co.jp/ETGate/", None),
    ("<div hidden>該当する銘柄はありません</div>",
     "https://site1.sbisec.co.jp/ETGate/", None),
    ("<div>該当する銘柄はありません</div>",
     "https://site1.sbisec.co.jp/ETGate/", "ticker_not_found"),
    ("<div>銘柄コードが正しくありません</div>",
     "https://site1.sbisec.co.jp/ETGate/", "ticker_not_found"),
    # CSS-hidden login form should NOT trigger auth_expired
    ("<form style='display:none'><input type='password'><input name='userid'></form>",
     "https://site1.sbisec.co.jp/ETGate/", None),
    # Login text without form structure should NOT trigger
    ("<div>ログイン履歴</div><div>パスワード管理について</div>",
     "https://site1.sbisec.co.jp/ETGate/", None),
])
def test_classify_page_state(html, url, expected):
    assert classify_page_state(html, url) == expected


def test_password_type_is_case_insensitive():
    """type='PASSWORD' must be detected as login form."""
    html = "<form action='/login'><input name='userid'><input type='PASSWORD'></form>"
    assert classify_page_state(html, "https://site1.sbisec.co.jp/ETGate/") == "auth_expired"


def test_visible_soup_strips_hidden_elements():
    html = """<div>visible</div><script>hidden</script>
    <div style="display:none">also hidden</div>
    <template>template content</template>
    <div hidden>hidden attr</div>"""
    soup = visible_soup(html)
    text = soup.get_text(" ", strip=True)
    assert "visible" in text
    assert "hidden" not in text
    assert "also hidden" not in text
    assert "template content" not in text
    assert "hidden attr" not in text
