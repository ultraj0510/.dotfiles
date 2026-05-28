"""Shared threshold constants for signal and backtest engines.

Centralises tuning parameters so signal_engine.py and backtest_engine.py
stay in sync without duplication.  When adjusting a threshold, change it
here and both production signal classification and historical backtest
simulation pick up the new value.
"""

# ── RSI ──────────────────────────────────────────────────────────────
RSI_LOWER = 30          # oversold threshold
RSI_UPPER = 70          # overbought threshold

# ── 52-week position ────────────────────────────────────────────────
POSITION_52W_LOWER = 25  # near 52w low (percentile)
POSITION_52W_UPPER = 85  # near 52w high (percentile)

# ── Momentum ────────────────────────────────────────────────────────
MOMENTUM_5D = 7.0        # 5-day return threshold for momentum BUY (%)
MOMENTUM_STRONG_VOL = 1.5  # volume ratio for "strong" momentum grade

# ── Breakdown ───────────────────────────────────────────────────────
BREAKDOWN_5D = -7.0      # 5-day return threshold for breakdown SELL (%)

# signal_engine.py momentum_breakdown: minimum volume ratio to fire
BREAKDOWN_VOL_GATE = 1.0

# backtest_engine.py DEFAULT_THRESHOLDS: volume ratio gate for
# momentum_breakdown in historical simulation.
# NOTE: intentionally different from BREAKDOWN_VOL_GATE — backtest
# engine uses a stricter gate (1.5 vs 1.0) to reduce false positives
# in historical runs where volume data may be less reliable.
BREAKDOWN_VOL = 1.5

# ── Drawdown ────────────────────────────────────────────────────────
DRAWDOWN_20D = -15.0     # 20-day return threshold for drawdown stop (%)

# ── Bollinger Bands ─────────────────────────────────────────────────
BB_PROXIMITY = 1.02      # close <= boll_lb * 1.02 = "near BB lower"
