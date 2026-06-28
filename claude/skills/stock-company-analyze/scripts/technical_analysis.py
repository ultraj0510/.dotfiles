"""Technical analysis wrapper for signal_engine + backtest_engine.

Bridges the stock-advisor signal engine and backtest engine
for use by the stock-company-analyze pipeline.
"""

import json
import math
import os
import subprocess
import sys
import tempfile

_STOCK_ADVISOR_SCRIPTS = "/Users/fujie/.claude/skills/stock-advisor/scripts"
if _STOCK_ADVISOR_SCRIPTS not in sys.path:
    sys.path.insert(0, _STOCK_ADVISOR_SCRIPTS)

# Add stock-advisor venv site-packages for pandas/yfinance dependencies
import glob as _glob
_venv_site = _glob.glob(
    "/Users/fujie/.claude/skills/stock-advisor/scripts/.venv/lib/python3.*/site-packages"
)
if _venv_site and _venv_site[0] not in sys.path:
    sys.path.insert(0, _venv_site[0])


def normalize_direction(signal_raw: str) -> str:
    if signal_raw in ("STRONG_BUY", "BUY", "HOLD_BUY"):
        return "BUY"
    if signal_raw in ("HOLD_SELL", "SELL", "STRONG_SELL"):
        return "SELL"
    return "HOLD"


def _safe_float(value, default=None):
    if value is None or value == "N/A":
        return default
    try:
        return float(value)
    except (TypeError, ValueError, AttributeError):
        return default


def _extract_indicators(raw_indicators: dict) -> dict:
    rsi = _safe_float(raw_indicators.get("rsi"))
    macd = _safe_float(raw_indicators.get("macd"))
    macds = _safe_float(raw_indicators.get("macds"))
    macdh = _safe_float(raw_indicators.get("macdh"))
    boll_ub = _safe_float(raw_indicators.get("boll_ub"))
    boll = _safe_float(raw_indicators.get("boll"))
    boll_lb = _safe_float(raw_indicators.get("boll_lb"))
    close = _safe_float(raw_indicators.get("close"))
    close_50_sma = _safe_float(raw_indicators.get("close_50_sma"))
    close_200_sma = _safe_float(raw_indicators.get("close_200_sma"))
    atr = _safe_float(raw_indicators.get("atr"))

    position_pct = None
    if close is not None and boll_ub is not None and boll_lb is not None:
        band_width = boll_ub - boll_lb
        if band_width > 0:
            position_pct = round((close - boll_lb) / band_width * 100, 2)

    volatility_annual_pct = None
    if atr is not None and close is not None and close > 0:
        daily_atr_pct = (atr / close) * 100
        volatility_annual_pct = round(daily_atr_pct * math.sqrt(252), 2)

    return {
        "rsi": rsi,
        "macd": {"line": macd, "signal": macds, "histogram": macdh},
        "bollinger": {
            "upper": boll_ub,
            "middle": boll,
            "lower": boll_lb,
            "position_pct": position_pct,
        },
        "sma_25": close_50_sma,
        "sma_75": close_200_sma,
        "volatility_annual_pct": volatility_annual_pct,
        "close": close,
        "atr": atr,
    }


def _run_backtest(ticker: str, date_str: str) -> dict:
    fd, tmpfile = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    python_bin = os.path.join(
        _STOCK_ADVISOR_SCRIPTS, ".venv", "bin", "python"
    )
    bt_script = os.path.join(_STOCK_ADVISOR_SCRIPTS, "backtest_engine.py")

    cmd = [
        python_bin, bt_script,
        "--ticker", ticker,
        "--strategy", "auto",
        "--execution-delay",
        "--end", date_str,
        "-o", tmpfile,
        "--wf-research",
        "--no-cache",
    ]

    try:
        subprocess.run(
            cmd, timeout=120, check=True, capture_output=True, text=True
        )
        with open(tmpfile) as f:
            data = json.load(f)
    except subprocess.TimeoutExpired:
        return {"error": "backtest timed out after 120s"}
    except subprocess.CalledProcessError as e:
        return {"error": f"backtest failed: {e.stderr or str(e)}"}
    except json.JSONDecodeError as e:
        return {"error": f"backtest output is not valid JSON: {e}"}
    except FileNotFoundError as e:
        return {"error": f"backtest script or python not found: {e}"}
    except Exception as e:
        return {"error": f"backtest error: {e}"}
    finally:
        if os.path.exists(tmpfile):
            try:
                os.unlink(tmpfile)
            except OSError:
                pass

    baseline = data.get("baseline", {})
    wf = data.get("walk_forward", {})
    consensus = wf.get("consensus", {})
    strategy_selection = data.get("strategy_selection", {})

    return {
        "sharpe": baseline.get("sharpe_ratio"),
        "sortino": baseline.get("sortino_ratio"),
        "max_drawdown_pct": baseline.get("max_drawdown"),
        "win_rate": baseline.get("win_rate"),
        "trade_count": baseline.get("trade_count"),
        "wf_verdict": consensus.get("verdict"),
        "wf_overfit_count": consensus.get("overfit_count"),
        "tradeable": strategy_selection.get("tradeable"),
    }


def run_technical_analysis(
    ticker: str, date_str: str, daily_bars=None, macro=None
) -> dict:
    from signal_engine import analyze_ticker as _signal_analyze_ticker

    raw = _signal_analyze_ticker(
        ticker, date_str, force_refresh=False, macro=macro
    )

    if "error" in raw:
        return {"error": raw["error"]}

    score = raw.get("score", {})
    signal_raw = score.get("recommendation", "HOLD")
    direction = normalize_direction(signal_raw)

    indicators = _extract_indicators(raw.get("indicators", {}))
    backtest = _run_backtest(ticker, date_str)

    return {
        "signal_raw": signal_raw,
        "direction": direction,
        "score": score,
        "trend_state": raw.get("trend_state"),
        "indicators": indicators,
        "signals": raw.get("signals", []),
        "backtest": backtest,
        "close": _safe_float(indicators.get("close")),
        "atr": _safe_float(indicators.get("atr")),
    }
