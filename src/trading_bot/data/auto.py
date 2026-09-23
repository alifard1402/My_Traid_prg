"""منبع داده خودکار — منابع را به ترتیب امتحان می‌کند.

لازم نیست بدانی سرورت به کدام صرافی دسترسی دارد: سرور داخل ایران معمولاً
فقط نوبیتکس را می‌بیند، سرور خارج از ایران معمولاً بایننس و یاهو را.
این منبع اولین منبعی را که جواب داد به خاطر می‌سپارد و دفعه بعد از همان
شروع می‌کند.
"""

from __future__ import annotations

import logging

import pandas as pd

from .base import DataSource

log = logging.getLogger("trading_bot.data")

#: ترتیب امتحان کردن منابع
DEFAULT_ORDER = ("nobitex", "binance", "yahoo")


class AutoSource(DataSource):
    name = "auto"

    #: آخرین منبعی که جواب داد (بین همه نمونه‌ها مشترک است)
    active: str | None = None

    def __init__(self, order: tuple[str, ...] = DEFAULT_ORDER) -> None:
        self.order = order

    def _candidates(self) -> list[str]:
        if AutoSource.active in self.order:
            return [AutoSource.active] + [s for s in self.order if s != AutoSource.active]
        return list(self.order)

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 1000) -> pd.DataFrame:
        from . import get_source  # جلوگیری از import حلقوی

        errors = []
        for name in self._candidates():
            try:
                df = get_source(name).fetch_ohlcv(symbol, timeframe, limit)
            except (ConnectionError, ValueError) as exc:
                errors.append(f"{name}: {str(exc).splitlines()[0]}")
                continue
            if AutoSource.active != name:
                log.info("منبع داده خودکار: از %s استفاده می‌شود.", name)
            AutoSource.active = name
            return df

        raise ConnectionError(
            "هیچ منبع داده‌ای در دسترس نبود:\n  " + "\n  ".join(errors)
        )
