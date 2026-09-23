"""تولید داده مصنوعی — برای وقتی که به اینترنت/صرافی دسترسی نداری.

داده کاملاً ساختگی است و ارزش تحلیلی ندارد؛ فقط برای این است که بتوانی
همین حالا ربات را اجرا کنی و ببینی چطور کار می‌کند.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import DataSource, is_gold, timeframe_to_minutes


class SampleSource(DataSource):
    """قیمت مصنوعی با حرکت تصادفی و چند دوره روندی."""

    name = "sample"

    def __init__(self, seed: int = 42, start_price: float | None = None) -> None:
        self.seed = seed
        self.start_price = start_price

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 1000) -> pd.DataFrame:
        minutes = timeframe_to_minutes(timeframe)
        rng = np.random.default_rng(self.seed)
        # طلا هم قیمت پایین‌تری دارد، هم نوسانش حدوداً نصف بیت‌کوین است.
        gold = is_gold(symbol)
        start_price = self.start_price or (2_600.0 if gold else 30_000.0)
        base_vol = 0.006 if gold else 0.012

        # روند را به چند رژیم تقسیم می‌کنیم: صعودی، نزولی، خنثی.
        n_regimes = max(3, limit // 250)
        drifts = rng.choice([0.0006, -0.0005, 0.0], size=n_regimes)
        drift = np.repeat(drifts, int(np.ceil(limit / n_regimes)))[:limit]

        vol = base_vol * np.sqrt(minutes / 240)
        returns = drift * (minutes / 240) + rng.normal(0, vol, limit)
        close = start_price * np.exp(np.cumsum(returns))

        # از قیمت بسته، یک کندل منطقی می‌سازیم.
        open_ = np.concatenate([[start_price], close[:-1]])
        wick = np.abs(rng.normal(0, vol * 0.7, limit)) * close
        high = np.maximum(open_, close) + wick
        low = np.minimum(open_, close) - wick
        volume = rng.lognormal(mean=4.0, sigma=0.5, size=limit)

        end = pd.Timestamp.now(tz="UTC").floor(f"{minutes}min")
        index = pd.date_range(end=end, periods=limit, freq=f"{minutes}min", name="timestamp")

        df = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
            index=index,
        )
        return self.validate(df)
