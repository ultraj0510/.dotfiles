from collections.abc import Callable
from datetime import datetime

import pandas as pd
import yfinance as yf


class PriceProviderError(RuntimeError):
    def __init__(self, code: str, retryable: bool, message: str):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class YahooPriceProvider:
    def __init__(self, ticker_factory: Callable = yf.Ticker):
        self._ticker_factory = ticker_factory

    def _fetch(self, symbol: str, start: datetime, end: datetime, interval: str) -> pd.DataFrame:
        try:
            frame = self._ticker_factory(symbol).history(
                start=start,
                end=end,
                interval=interval,
                auto_adjust=False,
                actions=True,
                repair=True,
                prepost=False,
                raise_errors=True,
            )
        except Exception as exc:
            raise PriceProviderError(
                "provider_failed",
                True,
                f"Yahoo Finance request failed for {symbol}",
            ) from exc
        if frame.empty:
            raise PriceProviderError(
                "no_data",
                False,
                f"Yahoo Finance returned no {interval} data for {symbol}",
            )
        return frame

    def fetch_daily(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        return self._fetch(symbol, start, end, "1d")

    def fetch_intraday(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        return self._fetch(symbol, start, end, "1h")
