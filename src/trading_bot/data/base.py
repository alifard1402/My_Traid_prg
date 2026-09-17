"""رابط مشترک منابع داده.

هر منبع داده (صرافی، فایل، داده مصنوعی) همین رابط را پیاده می‌کند،
پس بقیه برنامه نمی‌داند و برایش مهم نیست داده از کجا می‌آید.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

#: ستون‌هایی که هر منبع داده باید برگرداند
OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

#: تایم‌فریم‌های پشتیبانی‌شده و طولشان به دقیقه
TIMEFRAME_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


class DataSource(ABC):
    """منبع داده کندل (OHLCV)."""

    name: str = "base"

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 1000) -> pd.DataFrame:
        """آخرین `limit` کندل را برمی‌گرداند.

        خروجی: DataFrame با ایندکس زمانی (UTC) و ستون‌های OHLCV_COLUMNS،
        مرتب‌شده از قدیم به جدید.
        """

    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        """بررسی سلامت داده — داده خراب، نتیجه بک‌تست را بی‌معنا می‌کند."""
        missing = [c for c in OHLCV_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"ستون‌های گمشده در داده {self.name}: {missing}")

        df = df[OHLCV_COLUMNS].copy()
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df = df.dropna()

        # یک کندل سالم: high >= low و هر دو قیمتِ باز/بسته داخل این بازه است.
        sane = (
            (df["high"] >= df["low"])
            & (df["high"] >= df[["open", "close"]].max(axis=1))
            & (df["low"] <= df[["open", "close"]].min(axis=1))
            & (df["close"] > 0)
        )
        bad = int((~sane).sum())
        if bad:
            df = df[sane]
        if df.empty:
            raise ValueError(f"منبع {self.name} هیچ کندل سالمی برنگرداند.")
        return df


def timeframe_to_minutes(timeframe: str) -> int:
    if timeframe not in TIMEFRAME_MINUTES:
        raise ValueError(
            f"تایم‌فریم ناشناخته: {timeframe}. "
            f"مقادیر مجاز: {', '.join(TIMEFRAME_MINUTES)}"
        )
    return TIMEFRAME_MINUTES[timeframe]
