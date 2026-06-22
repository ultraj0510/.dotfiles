"""Deterministic technical and market metrics — no LLM involved."""
import math


def compute_metrics(daily_bars, intraday_bars, benchmark_bars):
    closes = [b["close"] for b in daily_bars]
    volumes = [b["volume"] for b in daily_bars]
    return {
        "returns": _compute_returns(closes),
        "moving_averages": _compute_mas(closes),
        "rsi": _rsi_summary(closes),
        "macd": _macd_summary(closes),
        "bollinger": _bollinger_summary(closes),
        "volatility": _volatility_summary(closes),
        "volume": _volume_summary(volumes),
        "topix_relative": _benchmark_relative(daily_bars, benchmark_bars) if benchmark_bars else None,
    }


def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return [None] * len(closes)
    rsi = [None] * period
    gains = sum(max(0, closes[i] - closes[i - 1]) for i in range(1, period + 1))
    losses = sum(max(0, closes[i - 1] - closes[i]) for i in range(1, period + 1))
    avg_gain = gains / period
    avg_loss = losses / period
    rsi.append(_rsi_value(avg_gain, avg_loss))
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = diff if diff > 0 else 0
        loss = -diff if diff < 0 else 0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        rsi.append(_rsi_value(avg_gain, avg_loss))
    return rsi


def _rsi_value(avg_gain, avg_loss):
    if avg_loss == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))


def compute_macd(closes, fast=12, slow=26, signal=9):
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = [f - s if f and s else None for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, signal)
    histogram = [m - s if m and s else None for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, histogram


def compute_bollinger(closes, period=20, stddev=2):
    sma = _sma(closes, period)
    upper = [None] * len(closes)
    lower = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1:i + 1]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / period
        std = math.sqrt(variance)
        upper[i] = mean + stddev * std
        lower[i] = mean - stddev * std
    return upper, sma, lower


def _ema(values, period):
    if len(values) < period:
        return [None] * len(values)
    ema = [None] * (period - 1)
    valid = [v for v in values[:period] if v is not None]
    sma = sum(valid) / len(valid) if valid else 0
    ema.append(sma)
    multiplier = 2 / (period + 1)
    for i in range(period, len(values)):
        v = values[i] if values[i] is not None else ema[-1]
        ema.append((v - ema[-1]) * multiplier + ema[-1])
    return ema


def _sma(values, period):
    result = [None] * (period - 1)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1:i + 1]
        if any(v is None for v in window):
            result.append(None)
        else:
            result.append(sum(window) / period)
    return result


def _compute_returns(closes):
    if len(closes) < 2:
        return {}
    total = round((closes[-1] / closes[0] - 1) * 100, 2)
    ret_20d = round((closes[-1] / closes[-20] - 1) * 100, 2) if len(closes) >= 20 else None
    return {"total_return_pct": total, "return_20d_pct": ret_20d}


def _compute_mas(closes):
    latest = closes[-1] if closes else None
    sma25 = _sma_value(closes, 25)
    sma75 = _sma_value(closes, 75)
    return {
        "sma_25": sma25,
        "sma_75": sma75,
        "price_vs_sma25_pct": round((latest / sma25 - 1) * 100, 2) if latest and sma25 else None,
        "price_vs_sma75_pct": round((latest / sma75 - 1) * 100, 2) if latest and sma75 else None,
    }


def _sma_value(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _rsi_summary(closes):
    rsi = compute_rsi(closes)
    return {"latest": round(rsi[-1], 1) if rsi and rsi[-1] is not None else None}


def _macd_summary(closes):
    macd_line, signal, histogram = compute_macd(closes)
    return {
        "macd_line": round(macd_line[-1], 4) if macd_line and macd_line[-1] is not None else None,
        "signal": round(signal[-1], 4) if signal and signal[-1] is not None else None,
        "histogram": round(histogram[-1], 4) if histogram and histogram[-1] is not None else None,
    }


def _bollinger_summary(closes):
    upper, middle, lower = compute_bollinger(closes)
    latest = closes[-1] if closes else None
    if latest and upper[-1] and lower[-1]:
        position = round((latest - lower[-1]) / (upper[-1] - lower[-1]) * 100, 1)
    else:
        position = None
    return {
        "upper": round(upper[-1], 2) if upper and upper[-1] else None,
        "middle": round(middle[-1], 2) if middle and middle[-1] else None,
        "lower": round(lower[-1], 2) if lower and lower[-1] else None,
        "position_pct": position,
    }


def _volatility_summary(closes):
    if len(closes) < 20:
        return {}
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    daily_sigma = math.sqrt(variance)
    annual_sigma = daily_sigma * math.sqrt(252)
    peak = closes[0]
    max_dd = 0.0
    for c in closes:
        if c > peak:
            peak = c
        dd = (peak - c) / peak
        if dd > max_dd:
            max_dd = dd
    return {
        "daily_sigma": round(daily_sigma, 6),
        "annual_sigma_pct": round(annual_sigma * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
    }


def _volume_summary(volumes):
    if len(volumes) < 20:
        return {}
    avg20 = sum(volumes[-20:]) / 20
    return {
        "latest": volumes[-1],
        "avg_20d": round(avg20, 0),
        "ratio_vs_avg": round(volumes[-1] / avg20, 2) if avg20 else None,
    }


def _benchmark_relative(daily_bars, benchmark_bars):
    if not benchmark_bars:
        return None
    bench_map = {b["date"]: b["close"] for b in benchmark_bars if b.get("date")}
    aligned = [(b["close"], bench_map[b["date"]]) for b in daily_bars if b.get("date") in bench_map]
    if len(aligned) < 2:
        return None
    stock_ret = aligned[-1][0] / aligned[0][0] - 1
    bench_ret = aligned[-1][1] / aligned[0][1] - 1
    return {
        "stock_return_pct": round(stock_ret * 100, 2),
        "topix_return_pct": round(bench_ret * 100, 2),
        "excess_return_pct": round((stock_ret - bench_ret) * 100, 2),
    }
