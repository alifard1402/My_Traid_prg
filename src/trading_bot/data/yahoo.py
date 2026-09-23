"""منبع داده یاهو فایننس — قیمت جهانی طلا، بدون نیاز به کلید.

نماد پیش‌فرض طلا اینجا GC=F است: قرارداد آتی طلا در بورس نیویورک (COMEX).
قیمتش چند دلار با قیمت نقدی (اسپات) فرق دارد، ولی حرکتش عملاً یکی است و
برای بک‌تست و تحلیل روند کاملاً مناسب است.

دو نکته:
  - بازار طلا آخر هفته‌ها بسته است؛ پس در داده، شنبه و یکشنبه کندلی نیست.
  - یاهو کندل ۴ ساعته ندارد؛ کندل‌های ۱ ساعته را می‌گیریم و خودمان
    ۴تا۴تا ادغامشان می‌کنیم.
  - یاهو IPهای ایران را معمولاً جواب نمی‌دهد؛ روی VPS خارج از ایران کار می‌کند.
"""

from __future__ import annotations

import time

import pandas as pd
import requests

from .base import GOLD_ALIASES, DataSource, timeframe_to_minutes

BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"

#: تایم‌فریم ما → (interval یاهو، تعداد کندل یاهو که یک کندل ما را می‌سازد)
INTERVAL = {
    "1m": ("1m", 1),
    "5m": ("5m", 1),
    "15m": ("15m", 1),
    "30m": ("30m", 1),
    "1h": ("60m", 1),
    "4h": ("60m", 4),
    "1d": ("1d", 1),
}

#: بیشترین سابقه‌ای که یاهو برای هر interval می‌دهد (روز)
MAX_HISTORY_DAYS = {"1m": 7, "5m": 59, "15m": 59, "30m": 59, "60m": 729, "1d": 36500}

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) trading-bot/0.2"}


class YahooSource(DataSource):
    name = "yahoo"
    ALIASES = {
        **{alias: "GC=F" for alias in GOLD_ALIASES},
        "PAXGUSDT": "PAXG-USD",
        "XAUTUSDT": "XAUT-USD",
    }

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 1000) -> pd.DataFrame:
        if timeframe not in INTERVAL:
            raise ValueError(f"یاهو تایم‌فریم {timeframe} را پشتیبانی نمی‌کند.")

        interval, group = INTERVAL[timeframe]
        minutes = timeframe_to_minutes(timeframe)
        # بازار ۵ روز در هفته باز است، پس بازه را ~۱.۶ برابر بزرگ‌تر می‌گیریم.
        span_days = limit * minutes / 1440 * 1.6 + 3
        span_days = min(span_days, MAX_HISTORY_DAYS[interval])
        now = int(time.time())

        ticker = self.resolve_symbol(symbol)
        try:
            resp = requests.get(
                BASE_URL + ticker,
                params={
                    "interval": interval,
                    "period1": now - int(span_days * 86400),
                    "period2": now,
                    "includePrePost": "false",
                },
                headers=HEADERS,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            raise ConnectionError(
                f"اتصال به یاهو فایننس ناموفق بود: {exc}\n"
                "اگر داخل ایران هستی طبیعی است — از --source nobitex استفاده کن."
            ) from exc

        df = self.parse(payload, ticker)
        if group > 1:
            df = resample(df, f"{minutes}min")
        return self.validate(df).tail(limit)

    @staticmethod
    def parse(payload: dict, ticker: str = "") -> pd.DataFrame:
        chart = payload.get("chart") or {}
        results = chart.get("result") or []
        if chart.get("error") or not results or not results[0].get("timestamp"):
            raise ValueError(f"یاهو داده‌ای برای {ticker} برنگرداند: {chart.get('error')}")

        result = results[0]
        quote = result["indicators"]["quote"][0]
        df = pd.DataFrame(
            {
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "close": quote.get("close"),
                "volume": quote.get("volume") or [0] * len(result["timestamp"]),
            },
            index=pd.to_datetime(result["timestamp"], unit="s", utc=True),
        )
        df.index.name = "timestamp"
        # یاهو برای لحظه‌هایی که معامله‌ای نبوده null می‌گذارد.
        df = df.dropna(subset=["open", "high", "low", "close"])
        df["volume"] = df["volume"].fillna(0)
        return df.astype(float)


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """کندل‌های کوچک را به کندل بزرگ‌تر تبدیل می‌کند (مثلاً ۱ ساعته → ۴ ساعته)."""
    out = df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return out.dropna(subset=["open", "close"])
