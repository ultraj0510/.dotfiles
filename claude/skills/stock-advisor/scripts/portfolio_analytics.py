"""Portfolio-level quantitative analytics: correlation matrix and stress testing.

Usage:
    python portfolio_analytics.py --portfolio path/to/portfolio.yaml
"""

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_utils import load_ohlcv


def compute_correlation_matrix(tickers: list, lookback_days: int = 252) -> dict:
    """Compute pairwise correlation matrix of daily returns."""
    if len(tickers) < 2:
        return {"error": "Need at least 2 tickers"}

    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    returns, failed = {}, []

    for t in tickers:
        try:
            ohlcv = load_ohlcv(t, today)
            if ohlcv is None or ohlcv.empty:
                failed.append(t)
                continue
            ohlcv = ohlcv.set_index("Date")
            ret = ohlcv["Close"].pct_change().dropna()
            if len(ret) > lookback_days:
                ret = ret.iloc[-lookback_days:]
            if len(ret) < 20:
                failed.append(t)
                continue
            returns[t] = ret
        except Exception:
            failed.append(t)

    valid = [t for t in tickers if t in returns]
    if len(valid) < 2:
        return {"error": f"Too few valid tickers: {valid}, failed: {failed}"}

    df = pd.DataFrame(returns)
    corr_matrix = df.corr()

    n = len(valid)
    upper_vals, max_pair = [], (None, None, 0)
    for i in range(n):
        for j in range(i + 1, n):
            val = corr_matrix.iloc[i, j]
            upper_vals.append(val)
            if abs(val) > abs(max_pair[2]):
                max_pair = (valid[i], valid[j], val)

    avg_corr = float(np.mean(upper_vals))
    return {
        "tickers": valid, "failed": failed,
        "matrix": {t1: {t2: round(corr_matrix.loc[t1, t2], 3) for t2 in valid} for t1 in valid},
        "avg_correlation": round(avg_corr, 3),
        "max_correlation": {"pair": [max_pair[0], max_pair[1]], "value": round(max_pair[2], 3)},
        "risk_concentration": "high" if abs(avg_corr) > 0.5 else ("medium" if abs(avg_corr) > 0.3 else "low"),
        "lookback_days": lookback_days,
    }


def compute_stress_test(portfolio: dict) -> dict:
    """Estimate portfolio loss under historical stress scenarios."""
    scenarios = {
        "2008_GFC": {"market_drop": -0.48, "vol_spike": 80, "description": "2008 Global Financial Crisis (TOPIX -48%)"},
        "2020_COVID": {"market_drop": -0.31, "vol_spike": 82, "description": "2020 COVID-19 Crash (TOPIX -31%)"},
        "2024_Aug_JP": {"market_drop": -0.20, "vol_spike": 50, "description": "2024 Aug Japan Rate-Hike (TOPIX -20%)"},
        "2019_JPY_Flash": {"market_drop": -0.05, "vol_spike": 30, "description": "2019 JPY Flash Crash"},
    }

    holdings = portfolio.get("holdings", [])
    if not holdings:
        return {"error": "No holdings"}

    total_value = sum(h.get("quantity", 0) * h.get("current_price", 0) for h in holdings)
    if total_value <= 0:
        return {"error": "Portfolio value is zero"}

    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    results = {}

    for name, params in scenarios.items():
        loss, impacts = 0.0, []
        for h in holdings:
            t, q, p = h.get("ticker"), h.get("quantity", 0), h.get("current_price", h.get("cost_price", 0))
            hv = q * p
            beta = 1.0
            try:
                sd = load_ohlcv(t, today)
                if sd is not None and not sd.empty:
                    sd = sd.set_index("Date")
                    sr = sd["Close"].pct_change().dropna()
                    topix = yf.download("^TOPX", period="1y", progress=False)
                    if not topix.empty:
                        tr = topix["Close"].pct_change().dropna()
                        ci = sr.index.intersection(tr.index)
                        if len(ci) > 60:
                            beta = float(np.cov(sr.loc[ci], tr.loc[ci])[0, 1] / np.var(tr.loc[ci]))
            except Exception:
                pass
            est_drop = params["market_drop"] * beta
            hl = hv * est_drop
            loss += hl
            impacts.append({"ticker": t, "beta": round(beta, 2), "drop_pct": round(est_drop * 100, 2), "loss": round(hl, 0)})
        impacts.sort(key=lambda x: abs(x["loss"]), reverse=True)
        results[name] = {
            "description": params["description"], "market_shock_pct": round(params["market_drop"] * 100, 1),
            "portfolio_loss": round(loss, 0), "loss_pct": round(loss / total_value * 100, 2),
            "worst_holdings": impacts[:3],
        }

    results["summary"] = {"portfolio_value": round(total_value, 0), "num_holdings": len(holdings)}
    return results


def main():
    p = argparse.ArgumentParser(description="Portfolio analytics")
    p.add_argument("--portfolio", required=True)
    p.add_argument("--output", "-o")
    a = p.parse_args()
    import yaml
    with open(a.portfolio) as f:
        pf = yaml.safe_load(f)
    holdings = pf.get("holdings", [])
    tickers = sorted(set(h.get("ticker", "") for h in holdings if h.get("ticker")))
    result = {}
    if len(tickers) >= 2:
        result["correlation"] = compute_correlation_matrix(tickers)
    result["stress_test"] = compute_stress_test(pf)
    out = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if a.output:
        os.makedirs(os.path.dirname(a.output) or ".", exist_ok=True)
        with open(a.output, "w") as f:
            f.write(out)
        print(f"Output written to {a.output}")
    else:
        print(out)


if __name__ == "__main__":
    main()
