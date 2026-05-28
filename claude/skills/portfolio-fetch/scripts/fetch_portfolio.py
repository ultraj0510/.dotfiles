#!/usr/bin/env python3
"""market-pulse: 保有銘柄データ取得スクリプト.

stock-price-analyze の分析モジュールを再利用し、全保有銘柄の
テクニカル指標・シグナル・信用リスク・含み損益を一括取得する。

使い方:
  python3 fetch_portfolio.py          # 要アクション銘柄のみ
  python3 fetch_portfolio.py --all    # 全銘柄詳細表示
  python3 fetch_portfolio.py --skip-sync  # SBI自動同期スキップ
"""

import argparse
import sys
import os
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# --- Python discovery ---
def _discover_python() -> str:
    """SKILL.md規定の順序でPythonを検出する。"""
    forced = os.environ.get("MORNING_CHECK_PYTHON")
    if forced:
        return forced

    candidates = [
        os.path.expanduser("~/code/deepcode/TradingAgents/.venv/bin/python3"),
        os.path.expanduser("~/code/playground/stock-price-analyze/.venv/bin/python3"),
        os.path.expanduser("~/code/playground/stock-price-analyze/venv312/bin/python3"),
        os.path.expanduser("~/code/playground/stock-price-analyze/venv/bin/python3"),
    ]
    for python in candidates:
        if os.path.isfile(python) and os.access(python, os.X_OK):
            return python

    return "python3"


PYTHON = _discover_python()

_STOCK_ANALYZE_DIR = os.path.expanduser("~/code/playground/stock-price-analyze")
if os.path.isdir(_STOCK_ANALYZE_DIR) and _STOCK_ANALYZE_DIR not in sys.path:
    sys.path.insert(0, _STOCK_ANALYZE_DIR)

import yaml


def load_portfolio(portfolio_path: str = None) -> dict:
    if portfolio_path is None:
        portfolio_path = os.path.join(_STOCK_ANALYZE_DIR, "portfolio.yaml")
    with open(portfolio_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def fetch_stock_data(ticker: str, fallback_price: float = None) -> dict | None:
    """1銘柄の株価・指標・シグナルを取得する。

    If yfinance fails but fallback_price is provided (e.g. from SBI sync),
    returns a minimal dict with the SBI price. This prevents ¥0/data-failure
    displays when the market is closed.
    """
    price = None
    rsi = bb_lower = bb_upper = ma20 = atr = 0.0
    signals = []
    signal_desc = ""
    market_phase = "neutral"
    surge = False

    try:
        from data.fetcher import get_stock_data
        from indicators.calculator import calculate_indicators, get_latest_values
        from signals.engine import check_signal, describe_signals

        df = get_stock_data(ticker, period="1y")
        if df is not None:
            df = calculate_indicators(df)
            values = get_latest_values(df)
            signals = check_signal(values)
            signal_desc = describe_signals(signals)

            p = values.get("price")
            if p is not None and not (isinstance(p, (int, float)) and p != p):
                price = float(p.iloc[0] if hasattr(p, "iloc") else p)

            rsi = round(float(values.get("rsi", 0) or 0), 1)
            bb_lower = round(float(values.get("bb_lower", 0) or 0), 0)
            bb_upper = round(float(values.get("bb_upper", 0) or 0), 0)
            ma20 = round(float(values.get("ma20", 0) or 0), 0)
            atr = round(float(values.get("atr", 0) or 0), 0)
            market_phase = values.get("market_phase", "neutral")
            surge = bool(values.get("surge_days", 0) > 0)
    except ImportError:
        pass

    # Use SBI-synced fallback price if yfinance failed
    if price is None and fallback_price and fallback_price > 0:
        price = fallback_price

    if price is None or price <= 0:
        return None

    return {
        "price": round(price, 0),
        "rsi": rsi,
        "bb_lower": bb_lower,
        "bb_upper": bb_upper,
        "ma20": ma20,
        "signals": signals,
        "signal_desc": signal_desc,
        "market_phase": market_phase,
        "atr": atr,
        "surge_detected": surge,
    }


def calc_credit_risks(holding: dict, current_price: float, account_margin_ratio: float | None = None) -> dict:
    """信用建玉のリスク情報を計算する。

    account_margin_ratio: SBI口座全体の委託保証金率（%）。追証判定は口座単位で行う。
    """
    try:
        from risk.margin import calculate_margin_risk, calculate_interest_cost, calculate_expiry
    except ImportError:
        return {}

    qty = holding.get("quantity", 0)
    cost = holding.get("cost_price", 0)
    result = {}

    margin = calculate_margin_risk(qty, cost, current_price)
    # 追証判定は口座全体の委託保証金率で判断（SBI: 最低保証金維持率20%）
    if account_margin_ratio is not None:
        margin["account_margin_ratio"] = account_margin_ratio
        margin["margin_call_triggered"] = account_margin_ratio < 20.0
    result["margin_risk"] = margin

    open_str = holding.get("open_date")
    if open_str:
        open_date = date.fromisoformat(open_str)
        interest = calculate_interest_cost(qty, cost, open_date)
        result["interest"] = interest

    expiry_str = holding.get("expiry_date")
    if expiry_str:
        expiry_date = date.fromisoformat(expiry_str)
        result["expiry"] = calculate_expiry(expiry_date)

    return result


def score_action(holding: dict, stock: dict | None, credit_risks: dict) -> int:
    """アクション優先度スコアを計算する（高いほど緊急）。"""
    score = 0
    if stock is None:
        return 99  # データ取得失敗は最優先

    # 信用期限が迫っている（max 40点）
    expiry = credit_risks.get("expiry", {})
    days = expiry.get("days_remaining", 999)
    if days < 30:
        score += 40
    elif days < 60:
        score += 20

    # 含み損が大きい（max 30点）
    cost = holding.get("cost_price", 0)
    qty = holding.get("quantity", 0)
    price = stock.get("price", cost)
    if cost > 0:
        pnl_pct = (price - cost) / cost * 100
        if pnl_pct < -15:
            score += 30
        elif pnl_pct < -8:
            score += 15
        elif pnl_pct < -3:
            score += 5

    # シグナルが強い（max 20点）
    n_signals = len(stock.get("signals", []))
    if n_signals >= 2:
        score += 20
    elif n_signals == 1:
        score += 10

    # 信用維持率が危険（max 10点）
    margin = credit_risks.get("margin_risk", {})
    if margin.get("margin_call_triggered"):
        score += 10
    elif margin.get("alert_triggered"):
        score += 5

    return score


def format_output(holdings: list, portfolios: list, show_all: bool = False):
    """SKILL.md Step 1 が要求する形式で出力する。"""
    account = portfolios.get("account", {})
    total_assets = account.get("total_assets", 0)
    available_cash = account.get("available_cash", 0)
    account_margin_ratio = account.get("margin_ratio")

    margin_str = f"  |  Margin: {account_margin_ratio:.1f}%" if account_margin_ratio else ""
    print(f"## Portfolio Snapshot {date.today().isoformat()}")
    print(f"Total Assets: ¥{total_assets:,}  |  Cash: ¥{available_cash:,}{margin_str}")
    print()

    actionable = []
    for h in holdings:
        ticker = h.get("ticker")
        name = h.get("name", ticker)
        pos_type = h.get("position_type", "現物")
        qty = h.get("quantity", 0)
        cost = h.get("cost_price", 0)

        fallback = h.get("current_price") or cost
        stock = fetch_stock_data(ticker, fallback_price=fallback)
        credit_risks = {}
        if pos_type == "信用":
            if stock:
                credit_risks = calc_credit_risks(h, stock["price"], account_margin_ratio)

        score = score_action(h, stock, credit_risks)
        has_action = score >= 5

        if has_action or show_all:
            actionable.append((score, ticker, name, h, stock, credit_risks, pos_type, qty, cost))

    actionable.sort(key=lambda x: x[0], reverse=True)

    if not actionable:
        print("## 全銘柄 正常（要アクションなし）")
        return

    # マクロ環境取得
    def _yf_close_vals(data):
        """yfinance >=0.5 returns MultiIndex columns; extract Close as 1-D array."""
        import pandas as pd
        if data.empty:
            return None
        close = data["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return close.values

    def _last_trading_date(data):
        """Extract the last trading date from yfinance data (works on weekends)."""
        if data.empty:
            return None
        ts = data.index[-1]
        return ts.date() if hasattr(ts, "date") else ts

    today = date.today()
    effective_date = today

    try:
        import yfinance as yf
        vix_data = yf.download("^VIX", period="5d", progress=False)
        vix_close = _yf_close_vals(vix_data)
        vix_val = float(vix_close[-1]) if vix_close is not None and len(vix_close) > 0 else None
        if not vix_data.empty:
            effective_date = _last_trading_date(vix_data)
    except Exception:
        vix_val = None

    try:
        import yfinance as yf
        sp500_data = yf.download("^GSPC", period="5d", progress=False)
        sp500_close = _yf_close_vals(sp500_data)
        if sp500_close is not None and len(sp500_close) >= 2:
            sp500_prev = float(sp500_close[-2])
            sp500_curr = float(sp500_close[-1])
            sp500_chg = round((sp500_curr - sp500_prev) / sp500_prev * 100, 2)
        else:
            sp500_chg = None
        if effective_date == today and not sp500_data.empty:
            effective_date = _last_trading_date(sp500_data)
    except Exception:
        sp500_chg = None

    data_note = ""
    if effective_date < today:
        data_note = f" (data as of {effective_date.isoformat()}, market closed)"
    print(f"## Macro Context{data_note}")
    print(f"VIX: {vix_val:.1f}" if vix_val else "VIX: N/A")
    print(f"S&P500 前日比: {sp500_chg:+.2f}%" if sp500_chg is not None else "S&P500: N/A")
    print()

    print(f"## 要アクション銘柄 ({len(actionable)}件)")
    print()

    for score, ticker, name, h, stock, credit_risks, pos_type, qty, cost in actionable:
        price = stock["price"] if stock else 0
        pnl = (price - cost) * qty if stock and cost else 0
        pnl_pct = round((price - cost) / cost * 100, 1) if stock and cost else 0

        print(f"### {name} ({ticker}) — Score: {score}")
        print(f"  Type: {pos_type}  |  Qty: {qty}株  |  Cost: ¥{cost:,.0f}  |  Price: ¥{price:,.0f}")
        print(f"  PnL: ¥{pnl:+,.0f} ({pnl_pct:+.1f}%)")

        if stock:
            print(f"  RSI: {stock['rsi']}  |  MA20: ¥{stock['ma20']:,.0f}  |  BB: ¥{stock['bb_lower']:,.0f}〜¥{stock['bb_upper']:,.0f}")
            print(f"  Signals: {stock['signal_desc']}  |  Phase: {stock['market_phase']}")
            if stock.get("surge_detected"):
                print(f"  [WARN] 急騰検出中")

        expiry = credit_risks.get("expiry", {})
        if expiry:
            print(f"  Expiry: {expiry.get('expiry_date')} ({expiry.get('days_remaining')}日) [{expiry.get('urgency')}]")

        margin = credit_risks.get("margin_risk", {})
        if margin:
            call_price = margin.get("margin_call_price", 0)
            print(f"  MarginCall Limit: ¥{call_price:,.0f}  |  Position PnL: {margin.get('current_margin_ratio'):.1f}%")
            if margin.get("margin_call_triggered"):
                print(f"  [CRITICAL] 口座委託保証金率 {margin.get('account_margin_ratio', 0):.1f}% < 20% → 追証発生中！")
            elif margin.get("account_margin_ratio"):
                print(f"  Account Margin: {margin['account_margin_ratio']:.1f}% (healthy)")

        interest = credit_risks.get("interest", {})
        if interest:
            print(f"  Interest: ¥{interest.get('total_interest'):,.0f} ({interest.get('holding_days')}日)")

        print()
        sys.stdout.flush()


# --- SBI sync ---

# Portfolio pages require the authenticated site1 host; www redirects to login
# with otherwise-valid Cookie headers in some sessions.
_SBI_PORTFOLIO_URL = "https://site1.sbisec.co.jp/ETGate/?_ControlID=WPLETpfR001Control&_PageID=DefaultPID&_ActionID=DefaultAID&_DataStoreID=DSWPLETpfR001Control&OutSide=on&getFlg=on&_scpr=intpr=hn_trade"
_SBI_PORTFOLIO_URL_DESKTOP = "https://site1.sbisec.co.jp/ETGate/?_ControlID=WPLETpfR001Control&_PageID=DefaultPID&_ActionID=DefaultAID&_DataStoreID=DSWPLETpfR001Control&OutSide=on&getFlg=on&_scpr=intpr=hn_trade"
_SBI_ACCOUNT_URL = "https://site1.sbisec.co.jp/ETGate/?_ControlID=WPLETacR001Control&_PageID=DefaultPID&_ActionID=DefaultAID&_DataStoreID=DSWPLETacR001Control&OutSide=on&getFlg=on&_scpr=intpr=hn_acc"

_MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"
_DESKTOP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
_SBI_TICKER_MAP = {
    "ＮＦ金価格": "1328.T",
    "日鉄鉱": "1515.T",
    "ＯＬＣ": "4661.T",
    "任天堂": "7974.T",
    "ＳＢＩ": "8473.T",
    "ＩＨＩ": "7013.T",
    "ソニーＦＧ": "8729.T",
}


def _parse_cookie_input(raw: str) -> dict[str, str]:
    raw = raw.strip()
    if not raw:
        return {}
    if raw.startswith("[") or raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            data = data.get("tokens", data)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        if isinstance(data, list):
            result: dict[str, str] = {}
            for obj in data:
                if isinstance(obj, dict) and obj.get("name") and obj.get("value") is not None:
                    result[str(obj["name"])] = str(obj["value"])
            return result
    tokens: dict[str, str] = {}
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            key, _, value = part.partition("=")
            tokens[key.strip()] = value.strip()
    return tokens


def _reconstruct_cookie_header(tokens: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in tokens.items())


def _cookie_source_candidates() -> list[Path]:
    return [
        Path(os.path.expanduser("~/.agents/skills/portfolio-auth/.tokens.json")),
        Path(os.path.expanduser("~/.agents/skills/portfolio-auth/.cookie")),
        Path(os.path.expanduser("~/.claude/skills/portfolio-auth/.tokens.json")),
        Path(os.path.expanduser("~/.claude/skills/portfolio-auth/.cookie")),
    ]


def _read_cookie_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    raw = path.read_text().strip()
    if path.name == ".tokens.json":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        tokens = data.get("tokens", data) if isinstance(data, dict) else {}
    else:
        tokens = _parse_cookie_input(raw)
    if not tokens:
        return None
    print(f"[INFO] SBI Cookie source: {path}", file=sys.stderr)
    return _reconstruct_cookie_header(tokens)


def _load_sbi_cookie() -> str | None:
    """SBI_COOKIE env var > .agents auth files > .claude auth files.

    SBI_COOKIE can be a JSON array of cookie objects or a raw cookie string.
    Returns a standard cookie header string (name=value; name=value).
    """
    env_val = os.environ.get("SBI_COOKIE", "").strip()
    if env_val:
        return _reconstruct_cookie_header(_parse_cookie_input(env_val))
    for path in _cookie_source_candidates():
        cookie = _read_cookie_file(path)
        if cookie:
            return cookie
    return None


def _raw_cookie_source() -> str:
    raw = os.environ.get("SBI_COOKIE", "").strip()
    if raw:
        return raw
    for path in _cookie_source_candidates():
        if path.is_file():
            return path.read_text().strip()
    return ""


def _read_sbi_cookies() -> list[dict]:
    """Read SBI cookies as Playwright-compatible objects with full attributes."""
    import json as _json

    raw = _raw_cookie_source()
    if not raw:
        return []

    # JSON array from Cookie-Editor export
    if raw.startswith("["):
        try:
            data = _json.loads(raw)
            cookies = []
            for obj in data:
                c = {"name": obj["name"], "value": obj["value"],
                     "domain": obj.get("domain", ".sbisec.co.jp"),
                     "path": obj.get("path", "/")}
                if obj.get("secure"):
                    c["secure"] = True
                if obj.get("httpOnly"):
                    c["httpOnly"] = True
                st = obj.get("sameSite")
                if st and st not in ("unspecified", None):
                    st = st.replace("_", "-").lower()
                    st_map = {"no-restriction": "None", "lax": "Lax", "strict": "Strict", "none": "None"}
                    c["sameSite"] = st_map.get(st, "Lax")
                cookies.append(c)
            return cookies
        except (_json.JSONDecodeError, KeyError):
            pass

    # Plain string format
    return [
        {"name": name, "value": value, "domain": ".sbisec.co.jp", "path": "/"}
        for name, value in _parse_cookie_input(raw).items()
    ]


def _classify_sbi_html(html: str, url: str = "") -> str | None:
    lowered_url = url.lower()
    lowered_html = html.lower()
    login_markers = [
        "login-entry",
        "ログインページです",
        "ログインしてください",
        "ユーザーネーム",
        "name=\"user_id\"",
        "name=\"password\"",
    ]
    if "login" in lowered_url or any(marker in lowered_html or marker in html for marker in login_markers):
        return "auth_expired"
    maintenance_markers = ["メンテナンス中", "ただいまメンテナンス"]
    if "maintenance" in lowered_url or any(marker in lowered_html or marker in html for marker in maintenance_markers):
        return "maintenance"
    return None


def _sbi_headers(cookie: str, user_agent: str | None = None) -> dict[str, str]:
    return {
        "Cookie": cookie,
        "User-Agent": user_agent or _DESKTOP_UA,
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Referer": "https://www.sbisec.co.jp/",
    }


def _fetch_sbi_page(cookie: str, url: str = None, user_agent: str = None) -> tuple[str | None, str]:
    """Fetch SBI portfolio page via Playwright, return (html, status).

    Uses headless Chromium to navigate SBI's internal redirect chain.
    Falls back to urllib if Playwright is unavailable.
    """
    if url is None:
        url = _SBI_PORTFOLIO_URL

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _fetch_sbi_page_urllib(cookie, url, user_agent)  # urllib uses cookie string

    cookie_list = _read_sbi_cookies()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            context = browser.new_context(
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
            )
            print(f"[DEBUG] Setting {len(cookie_list)} cookies, JSESSIONID={'...' if any(c['name']=='JSESSIONID' for c in cookie_list) else 'MISSING'}", file=sys.stderr)
            context.add_cookies(cookie_list)
            page = context.new_page()

            # Hide automation
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            # Navigate to portfolio page directly
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            current_url = page.url
            if "login" in current_url.lower():
                browser.close()
                return (None, "auth_expired")

            html = page.content()
            browser.close()

            html_status = _classify_sbi_html(html, current_url)
            if html_status:
                return (None, html_status)
            if len(html) < 5000:
                return (None, "auth_expired")
            return (html, "ok")
    except Exception as e:
        print(f"[WARN] Playwright fetch failed: {e}", file=sys.stderr)
        return (None, "http_error")


def _fetch_sbi_page_urllib(cookie: str, url: str, user_agent: str) -> tuple[str | None, str]:
    """Fallback: fetch SBI page via urllib (no JS rendering)."""
    import urllib.request, urllib.error
    if user_agent is None:
        user_agent = _MOBILE_UA
    req = urllib.request.Request(url, headers=_sbi_headers(cookie, user_agent))
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if resp.getcode() != 200 or len(raw) < 1000:
                return (None, "auth_expired" if len(raw) < 1000 else "http_error")
            for enc in ["cp932", "shift_jis", "utf-8"]:
                try:
                    html = raw.decode(enc)
                    status = _classify_sbi_html(html, resp.geturl())
                    return (None, status) if status else (html, "ok")
                except UnicodeDecodeError:
                    continue
            html = raw.decode("cp932", errors="replace")
            status = _classify_sbi_html(html, resp.geturl())
            return (None, status) if status else (html, "ok")
    except Exception as e:
        print(f"[WARN] urllib fetch failed: {e}", file=sys.stderr)
        return (None, "http_error")


def _parse_sbi_holdings(html: str) -> tuple[list[dict], dict]:
    """Parse SBI portfolio HTML. Returns (holdings, account)."""
    import re

    holdings = []
    account: dict[str, float] = {}

    # Remove scripts/styles
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)

    # --- Account summary ---
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)

    # 現金残高等 (cash)
    m = re.search(r"現金残高等\s+([\d,]+)", text)
    if m:
        account["available_cash"] = float(m.group(1).replace(",", ""))

    # 建代金合計(B)
    m = re.search(r"建代金合計[（(]B[)）]\s+([\d,]+)", text)
    if m:
        account["margin_principal"] = float(m.group(1).replace(",", ""))

    # 委託保証金率
    m = re.search(r"委託保証金率[（(]A/B[)）][×x]\s*100\s+([\d,.]+)%", text)
    if m:
        account["margin_ratio"] = float(m.group(1).replace(",", ""))

    # 買付余力
    m = re.search(r"買付余力[（(]2営業日後[)）]\s+([\d,]+)", text)
    if m:
        account["buying_power"] = float(m.group(1).replace(",", ""))

    # 実質保証金(A)
    m = re.search(r"実質保証金[（(]A[)）]\s+([\d,]+)", text)
    if m:
        account["margin_collateral"] = float(m.group(1).replace(",", ""))

    # Total assets: look for the large number near 保有資産評価 or the total after ポートフォリオ
    m = re.search(r"保有資産評価[\s\S]*?([\d,]{7,})", text)
    if m:
        account["total_assets"] = float(m.group(1).replace(",", ""))

    # --- Spot holdings ---
    # Pattern: ticker_code name --/--/-- quantity cost_price current_price ...
    spot_pattern = re.compile(
        r"(\d{3,4}[A-Z]?)\s+"  # ticker (3-4 digits + optional letter, e.g. 285A, 7013)
        r"(\S+?)\s+"  # name
        r"[0-9\-/]+\s+"  # buy date or --/--/--
        r"([\d,]+)\s+"  # quantity
        r"([\d,.]+)\s+"  # cost price
        r"([\d,]+)\s+"  # current price
    )

    # Find spot section (現物/特定預り or 現物/NISA or 現物/一般預り)
    spot_section_pattern = re.compile(
        r"株式[（(]現物/(?:特定預り|NISA|一般預り)[）)]"
    )
    spot_ranges = []
    for m in spot_section_pattern.finditer(html):
        spot_ranges.append(m.start())
    # Also find the end of the spot data (信用 section start or 投資信託)
    credit_marker = html.find("株式（信用）")
    if credit_marker < 0:
        credit_marker = html.find("株式(信用)")
    if credit_marker < 0:
        credit_marker = html.find("信用建玉")

    # Parse spot sections
    for i, start in enumerate(spot_ranges):
        end = spot_ranges[i + 1] if i + 1 < len(spot_ranges) else credit_marker
        if end < 0 or end <= start:
            end = start + 20000
        section_html = html[start:end]
        section_text = re.sub(r"<[^>]+>", " ", section_html)
        section_text = re.sub(r"&nbsp;", " ", section_text)
        section_text = re.sub(r"\s+", " ", section_text)

        # Determine account type
        if "NISA（成長投資枠）" in section_html or "NISA(成長投資枠)" in section_html:
            account_type = "NISA成長"
        elif "NISA（つみたて投資枠）" in section_html or "NISA(つみたて投資枠)" in section_html:
            account_type = "NISAつみたて"
        elif "一般預り" in section_html:
            account_type = "一般"
        else:
            account_type = "特定"

        for sm in spot_pattern.finditer(section_text):
            ticker_code = sm.group(1)
            name = sm.group(2)
            qty = float(sm.group(3).replace(",", ""))
            cost = float(sm.group(4).replace(",", ""))
            price = float(sm.group(5).replace(",", ""))

            # Map name to ticker
            ticker = _SBI_TICKER_MAP.get(name, f"{ticker_code}.T")

            holdings.append({
                "ticker": ticker,
                "name": name,
                "position_type": "現物",
                "account_type": account_type,
                "quantity": int(qty),
                "cost_price": cost,
                "current_price": price,
            })

    # --- Margin holdings ---
    if credit_marker > 0:
        credit_end = html.find("投資信託", credit_marker)
        if credit_end < 0:
            credit_end = len(html)
        credit_html = html[credit_marker:credit_end]
        credit_text = re.sub(r"<[^>]+>", " ", credit_html)
        credit_text = re.sub(r"&nbsp;", " ", credit_text)
        credit_text = re.sub(r"\s+", " ", credit_text)

        # Pattern: ticker name 買建/売建 exchange/term date qty cost price ...
        margin_pattern = re.compile(
            r"(\d{3,4}[A-Z]?)\s+"
            r"(\S+?)\s+"
            r"(?:買建|売建)\s+"
            r"\S+?\s+"  # exchange/term (e.g., 東/6ヶ)
            r"([0-9\-/]+)\s+"  # open date
            r"([\d,]+)\s+"  # quantity
            r"([\d,.]+)\s+"  # cost price
            r"([\d,]+)"  # current price
        )

        for mm in margin_pattern.finditer(credit_text):
            ticker_code = mm.group(1)
            name = mm.group(2)
            open_date = mm.group(3)
            qty = float(mm.group(4).replace(",", ""))
            cost = float(mm.group(5).replace(",", ""))
            price = float(mm.group(6).replace(",", ""))

            ticker = _SBI_TICKER_MAP.get(name, f"{ticker_code}.T")

            # Parse date (skip "--/--/--" placeholders)
            open_date_iso = None
            if open_date and "/" in open_date and not open_date.startswith("--"):
                parts = [p for p in open_date.split("/") if p.strip() and not p.strip().startswith("-")]
                if len(parts) == 3:
                    try:
                        y, m, d = parts
                        y = f"20{y}" if len(y) == 2 else y
                        datetime.strptime(f"{y}-{m}-{d}", "%Y-%m-%d")
                        open_date_iso = f"{y}-{m}-{d}"
                    except ValueError:
                        open_date_iso = None

            holdings.append({
                "ticker": ticker,
                "name": name,
                "position_type": "信用",
                "quantity": int(qty),
                "cost_price": cost,
                "current_price": price,
                "open_date": open_date_iso,
            })

    return holdings, account


def _parse_sbi_account(html: str) -> dict[str, float]:
    """Parse SBI account page HTML for account summary."""
    import re

    account: dict[str, float] = {}
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)

    # 保有資産評価 section: 現金残高等 X 株式 Y 投資信託 Z 建玉評価損益額 W 計 TOTAL
    # Example: 現金残高等 505,828 株式 17,107,150 投資信託 823,227 建玉評価損益額 ... -652,910 計 17,783,295
    m = re.search(r"現金残高等\s+([\d,]+)\s+株式\s+([\d,]+)", text)
    if m:
        account["available_cash"] = float(m.group(1).replace(",", ""))
        account["stock_value"] = float(m.group(2).replace(",", ""))

    m = re.search(r"計\s+([\d,]{7,})", text)
    if m:
        account["total_assets"] = float(m.group(1).replace(",", ""))

    # Margin section
    m = re.search(r"建代金合計[（(]B[)）]\s+([\d,]+)", text)
    if m:
        account["margin_principal"] = float(m.group(1).replace(",", ""))

    m = re.search(r"委託保証金率\S*\s+([\d,.]+)\s*[%％]", text)
    if m:
        account["margin_ratio"] = float(m.group(1).replace(",", ""))

    m = re.search(r"買付余力[（(]2営業日後[)）]\s+([\d,]+)", text)
    if m:
        account["buying_power"] = float(m.group(1).replace(",", ""))

    m = re.search(r"実質保証金[（(]A[)）]\s+([\d,]+)", text)
    if m:
        account["margin_collateral"] = float(m.group(1).replace(",", ""))

    return account


def _merge_holdings(existing: list, sbi_holdings: list) -> list | None:
    """Merge SBI holdings into existing data while preserving manual metadata."""
    if len(sbi_holdings) < len(existing) * 0.5:
        print(
            f"[WARN] SBI holdings ({len(sbi_holdings)}) < 50% of existing "
            f"({len(existing)}). Merge aborted to prevent data loss.",
            file=sys.stderr,
        )
        return None

    def key_for(holding: dict) -> tuple:
        if holding.get("position_type", "現物") == "信用":
            return (
                holding.get("ticker"),
                holding.get("position_type", "現物"),
                holding.get("open_date"),
            )
        return (
            holding.get("ticker"),
            holding.get("position_type", "現物"),
            holding.get("account_type"),
        )

    existing_index = {key_for(h): h for h in existing}
    merged = []
    for sbi_h in sbi_holdings:
        old = existing_index.get(key_for(sbi_h), {})
        item = dict(old)
        item.update(sbi_h)
        merged.append(item)
    return merged


def sync_from_sbi(portfolio_path: str) -> str:
    """Sync holdings and account data from SBI. Returns status string."""
    cookie = _load_sbi_cookie()
    if not cookie:
        return "no_cookie"

    # Fetch holdings from portfolio page (mobile UA first, desktop as fallback)
    html, fetch_status = _fetch_sbi_page(cookie)
    if fetch_status in ("login_page", "auth_expired"):
        print("[AUTH_EXPIRED] Cookie rejected by SBI", file=sys.stderr)
        return "auth_expired"
    if fetch_status == "maintenance":
        print("[INFO] SBIサイトがメンテナンス中です。しばらく待ってから再実行してください。", file=sys.stderr)
        return "maintenance"
    if html is None:
        return "network_error"

    holdings, _ = _parse_sbi_holdings(html)
    html_status = _classify_sbi_html(html)
    if html_status:
        return html_status
    if not holdings:
        # Mobile page may be JS-rendered SPA. Retry with desktop UA.
        print("[INFO] Mobile parse returned 0 holdings, retrying with desktop UA...", file=sys.stderr)
        html2, status2 = _fetch_sbi_page(cookie, url=_SBI_PORTFOLIO_URL_DESKTOP, user_agent=_DESKTOP_UA)
        if status2 == "auth_expired":
            print("[AUTH_EXPIRED] Cookie rejected by SBI desktop page", file=sys.stderr)
            return "auth_expired"
        if html2:
            holdings, _ = _parse_sbi_holdings(html2)
            if holdings:
                html = html2  # use desktop response for debug saving
    if not holdings:
        print("[WARN] SBIから保有銘柄を抽出できませんでした。", file=sys.stderr)
        # Save raw HTML for debugging pattern mismatch
        debug_path = "/tmp/sbi_debug.html"
        try:
            with open(debug_path, "w", encoding="utf-8") as df:
                df.write(html)
            print(f"[DEBUG] SBI HTML saved to {debug_path} ({len(html)} chars)", file=sys.stderr)
        except Exception:
            pass
        return "parse_error"

    # Fetch account data from account page (desktop UA for richer data)
    import urllib.request
    import urllib.error
    account: dict[str, float] = {}
    try:
        req = urllib.request.Request(
            _SBI_ACCOUNT_URL,
            headers=_sbi_headers(cookie, _DESKTOP_UA),
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            acc_html = raw.decode("cp932", errors="replace")
        account = _parse_sbi_account(acc_html)
    except Exception as e:
        print(f"[WARN] SBI account page fetch failed: {e}", file=sys.stderr)

    # Load existing portfolio to preserve any manual metadata
    existing = {}
    if os.path.isfile(portfolio_path):
        try:
            with open(portfolio_path, encoding="utf-8") as f:
                existing = yaml.safe_load(f) or {}
        except Exception:
            pass

    existing_account = existing.get("account", {})
    # SBI is authoritative: only fall back to existing if SBI returns None.
    # Using `or` would treat 0 as falsy, masking a true zero balance.
    for key in ("total_assets", "available_cash", "margin_ratio", "buying_power", "margin_principal"):
        val = account.get(key)
        if val is not None:
            existing_account[key] = val

    # Merge holdings: SBI is truth for qty/price; preserve manual metadata
    existing_holdings = existing.get("holdings", [])
    if existing_holdings:
        merged = _merge_holdings(existing_holdings, holdings)
        if merged is None:
            return "parse_error"
    else:
        merged = holdings

    portfolio = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "last_successful_sync_at": datetime.now(timezone.utc).isoformat(),
        "last_sync_source": "SBI",
        "sync_status": "ok",
        "account": existing_account,
        "holdings": merged,
    }

    os.makedirs(os.path.dirname(portfolio_path), exist_ok=True)
    tmp_path = f"{portfolio_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(portfolio, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    os.replace(tmp_path, portfolio_path)

    print(f"[OK] SBI同期完了: {len(holdings)}銘柄", file=sys.stderr)
    return "ok"


def main():
    parser = argparse.ArgumentParser(description="market-pulse データ取得")
    parser.add_argument("--all", action="store_true", help="全銘柄詳細表示")
    parser.add_argument("--skip-sync", action="store_true", help="SBI自動同期スキップ")
    parser.add_argument("--use-cache-on-fail", action="store_true", help="SBI同期失敗時にキャッシュ表示を続行")
    args = parser.parse_args()

    portfolio_path = os.path.join(_STOCK_ANALYZE_DIR, "portfolio.yaml")

    # SBI自動同期
    cookie = _load_sbi_cookie()
    if not args.skip_sync and cookie:
        status = sync_from_sbi(portfolio_path)
        if status != "ok":
            if args.use_cache_on_fail:
                last_upd = "不明"
                if os.path.isfile(portfolio_path):
                    try:
                        cached = load_portfolio(portfolio_path)
                        last_upd = cached.get("last_successful_sync_at") or cached.get("last_updated", "不明")
                    except Exception:
                        pass
                print(f"[NOTICE] SBI同期に失敗したためキャッシュデータを表示します（status: {status}, 最終SBI同期: {last_upd}）")
            elif status == "auth_expired":
                print("[AUTH_EXPIRED] SBIセッションが切れています。", file=sys.stderr)
                sys.exit(2)
            else:
                print(f"[ERROR] SBI同期に失敗しました ({status})。", file=sys.stderr)
                sys.exit(1)
        print()
    elif not args.skip_sync and not cookie:
        print("[WARN] SBI_COOKIEが設定されていません。", file=sys.stderr)

    if not os.path.isfile(portfolio_path):
        print(f"[ERROR] portfolio.yaml not found at {portfolio_path}", file=sys.stderr)
        sys.exit(1)

    portfolio = load_portfolio(portfolio_path)
    holdings = portfolio.get("holdings", [])

    if not holdings:
        print("## 保有銘柄なし")
        return

    format_output(holdings, portfolio, show_all=args.all)


if __name__ == "__main__":
    main()
