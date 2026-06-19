"""Tests for url_cleaner module."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from url_cleaner import clean_url


def test_removes_sensitive_query_params():
    url = "https://site1.sbisec.co.jp/ETGate/?token=secret123&page=1&enc=abcdef"
    result = clean_url(url)
    assert "token" not in result
    assert "enc" not in result
    assert "page=1" in result


def test_removes_hash_params():
    url = "https://site1.sbisec.co.jp/ETGate/?ahash=abc&hhash=def&ihash=ghi&keep=1"
    result = clean_url(url)
    assert "ahash" not in result
    assert "hhash" not in result
    assert "ihash" not in result
    assert "keep=1" in result


def test_preserves_harmless_params():
    url = "https://site1.sbisec.co.jp/ETGate/?stock_sec_code_mul=3932&_PageID=DefaultPID"
    result = clean_url(url)
    assert "stock_sec_code_mul=3932" in result
    assert "_PageID=DefaultPID" in result


def test_url_without_query():
    url = "https://site1.sbisec.co.jp/ETGate/"
    result = clean_url(url)
    assert result == url


def test_url_with_fragment():
    url = "https://site1.sbisec.co.jp/ETGate/#section"
    result = clean_url(url)
    assert result == "https://site1.sbisec.co.jp/ETGate/"


def test_removes_all_sensitive_params_combined():
    url = "https://example.com/?token=x&enc=x&ahash=x&hhash=x&ihash=x&safe=keep"
    result = clean_url(url)
    for param in ["token", "enc", "ahash", "hhash", "ihash"]:
        assert param not in result
    assert "safe=keep" in result
