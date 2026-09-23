"""منبع داده نوبیتکس — از داخل ایران بدون فیلتر/تحریم در دسترس است.

از API عمومی نمودار (فرمت UDF تریدینگ‌ویو) استفاده می‌کند و برای
گرفتن قیمت به هیچ کلید API نیازی ندارد.
نمادها: BTCUSDT، BTCIRT، ETHUSDT، ETHIRT، ...
"""

from __future__ import annotations

import time

import pandas as pd
import requests

from .base import GOLD_ALIASES, DataSource, timeframe_to_minutes

BASE_URL = "https://api.nobitex.ir"

#: نگاشت تایم‌فریم ما به resolution نوبیتکس
RESOLUTION = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "4h": "240",
    "1d": "D",
}


class NobitexSource(DataSource):
    name = "nobitex"
    ALIASES = {alias: "PAXGUSDT" for alias in GOLD_ALIASES}

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 1000) -> pd.DataFrame:
        if timeframe not in RESOLUTION:
            raise ValueError(f"نوبیتکس تایم‌فریم {timeframe} را پشتیبانی نمی‌کند.")

        minutes = timeframe_to_minutes(timeframe)
        to_ts = int(time.time())
        # کمی حاشیه می‌گیریم چون بعضی کندل‌ها ممکن است خالی باشند.
        from_ts = to_ts - int(limit * minutes * 60 * 1.3)

        url = f"{BASE_URL}/market/udf/history"
        params = {
            "symbol": self.resolve_symbol(symbol),
            "resolution": RESOLUTION[timeframe],
            "from": from_ts,
            "to": to_ts,
        }
        try:
            resp = requests.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            raise ConnectionError(
                f"اتصال به نوبیتکس ناموفق بود: {exc}\n"
                "اینترنت را چک کن، یا با --source sample روی داده مصنوعی کار کن."
            ) from exc

        if payload.get("s") != "ok" or not payload.get("t"):
            raise ValueError(
                f"نوبیتکس داده‌ای برای {symbol} برنگرداند "
                f"(پاسخ: {payload.get('s')}). نماد را چک کن؛ مثلاً BTCUSDT یا BTCIRT."
            )

        df = pd.DataFrame(
            {
                "open": payload["o"],
                "high": payload["h"],
                "low": payload["l"],
                "close": payload["c"],
                "volume": payload.get("v", [0] * len(payload["t"])),
            },
            index=pd.to_datetime(payload["t"], unit="s", utc=True),
        ).astype(float)
        df.index.name = "timestamp"
        return self.validate(df).tail(limit)
