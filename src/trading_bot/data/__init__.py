"""لایه داده — گرفتن کندل از منابع مختلف با یک رابط مشترک."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .auto import AutoSource
from .base import OHLCV_COLUMNS, DataSource, is_gold, timeframe_to_minutes
from .binance import BinanceSource
from .nobitex import NobitexSource
from .sample import SampleSource
from .yahoo import YahooSource

SOURCES: dict[str, type[DataSource]] = {
    "auto": AutoSource,
    "nobitex": NobitexSource,
    "binance": BinanceSource,
    "yahoo": YahooSource,
    "sample": SampleSource,
}

CACHE_DIR = Path("data/cache")


def get_source(name: str) -> DataSource:
    """ساخت منبع داده از روی نامش."""
    if name not in SOURCES:
        raise ValueError(
            f"منبع داده ناشناخته: {name}. مقادیر مجاز: {', '.join(SOURCES)}"
        )
    return SOURCES[name]()


def cache_path(source: str, symbol: str, timeframe: str) -> Path:
    return CACHE_DIR / f"{source}_{symbol.upper()}_{timeframe}.csv"


def save_cache(df: pd.DataFrame, source: str, symbol: str, timeframe: str) -> Path:
    path = cache_path(source, symbol, timeframe)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path)
    return path


def load_cache(source: str, symbol: str, timeframe: str) -> pd.DataFrame:
    path = cache_path(source, symbol, timeframe)
    if not path.exists():
        raise FileNotFoundError(
            f"فایل داده ذخیره‌شده پیدا نشد: {path}\n"
            f"اول اجرا کن: python -m trading_bot fetch"
        )
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    return df[OHLCV_COLUMNS]


def load_ohlcv(
    source: str, symbol: str, timeframe: str, limit: int = 1000, use_cache: bool = True
) -> pd.DataFrame:
    """کندل‌ها را می‌گیرد؛ اگر شبکه در دسترس نبود سراغ فایل ذخیره‌شده می‌رود."""
    try:
        df = get_source(source).fetch_ohlcv(symbol, timeframe, limit)
        if use_cache and source != "sample":
            save_cache(df, source, symbol, timeframe)
        return df
    except (ConnectionError, ValueError):
        if use_cache and cache_path(source, symbol, timeframe).exists():
            return load_cache(source, symbol, timeframe)
        raise


__all__ = [
    "DataSource", "SampleSource", "NobitexSource", "BinanceSource", "YahooSource",
    "AutoSource", "is_gold",
    "SOURCES", "get_source", "load_ohlcv", "load_cache", "save_cache",
    "cache_path", "timeframe_to_minutes", "OHLCV_COLUMNS",
]
