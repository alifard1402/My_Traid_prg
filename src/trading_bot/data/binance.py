"""منبع داده بایننس — API عمومی، بدون نیاز به کلید.

هشدار: بایننس IPهای ایران را مسدود می‌کند. این منبع فقط از روی سرور
خارج از ایران (VPS) کار می‌کند. از داخل ایران از NobitexSource استفاده کن.
"""

from __future__ import annotations

import pandas as pd
import requests

from .base import DataSource

BASE_URL = "https://api.binance.com"

INTERVAL = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}


class BinanceSource(DataSource):
    name = "binance"

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 1000) -> pd.DataFrame:
        if timeframe not in INTERVAL:
            raise ValueError(f"بایننس تایم‌فریم {timeframe} را پشتیبانی نمی‌کند.")

        try:
            resp = requests.get(
                f"{BASE_URL}/api/v3/klines",
                params={
                    "symbol": symbol.upper(),
                    "interval": INTERVAL[timeframe],
                    "limit": min(limit, 1000),  # سقف مجاز بایننس در هر درخواست
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            rows = resp.json()
        except requests.RequestException as exc:
            raise ConnectionError(
                f"اتصال به بایننس ناموفق بود: {exc}\n"
                "اگر داخل ایران هستی این طبیعی است — از --source nobitex استفاده کن."
            ) from exc

        if not rows:
            raise ValueError(f"بایننس داده‌ای برای {symbol} برنگرداند.")

        df = pd.DataFrame(
            rows,
            columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades",
                "taker_base", "taker_quote", "ignore",
            ],
        )
        df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df.index.name = "timestamp"
        return self.validate(df.astype({c: float for c in ["open", "high", "low", "close", "volume"]}))
