"""منبع داده بایننس — API عمومی، بدون نیاز به کلید.

هشدار: بایننس IPهای ایران را مسدود می‌کند. این منبع فقط از روی سرور
خارج از ایران (VPS) کار می‌کند. از داخل ایران از NobitexSource استفاده کن.
"""

from __future__ import annotations

import pandas as pd
import requests

from .base import GOLD_ALIASES, DataSource

#: آدرس اصلی + آینه عمومی داده‌های بازار (گاهی وقتی اصلی مسدود است، آینه جواب می‌دهد)
BASE_URLS = ("https://api.binance.com", "https://data-api.binance.vision")

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
    ALIASES = {alias: "PAXGUSDT" for alias in GOLD_ALIASES}

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 1000) -> pd.DataFrame:
        if timeframe not in INTERVAL:
            raise ValueError(f"بایننس تایم‌فریم {timeframe} را پشتیبانی نمی‌کند.")

        params = {
            "symbol": self.resolve_symbol(symbol),
            "interval": INTERVAL[timeframe],
            "limit": min(limit, 1000),  # سقف مجاز بایننس در هر درخواست
        }
        last_error: Exception | None = None
        for base_url in BASE_URLS:
            try:
                resp = requests.get(f"{base_url}/api/v3/klines", params=params, timeout=self.timeout)
                resp.raise_for_status()
                rows = resp.json()
                break
            except requests.RequestException as exc:
                last_error = exc
        else:
            raise ConnectionError(
                f"اتصال به بایننس ناموفق بود: {last_error}\n"
                "اگر داخل ایران هستی این طبیعی است — از --source nobitex استفاده کن."
            ) from last_error

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
