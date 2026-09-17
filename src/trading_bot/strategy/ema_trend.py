"""استراتژی «تقاطع میانگین متحرک با فیلتر روند».

منطق ساده و کلاسیک است، عمداً:

  ورود (خرید):
    ۱. میانگین سریع از پایینِ میانگین کند به بالا عبور کند  → شروع حرکت صعودی
    ۲. و قیمت بالای میانگین بلندمدت (۲۰۰) باشد            → روند کلی صعودی است

  خروج:
    - میانگین سریع به زیر میانگین کند برگردد، یا
    - حد ضرر / حد سود بخورد (این را موتور بک‌تست مدیریت می‌کند)

شرط دومِ ورود مهم‌ترین قسمت است: تقاطعِ تنها، در بازارِ رِنج سیگنال‌های
دروغینِ پشت‌سرهم می‌دهد و با کارمزد، حساب را می‌خورد.

این یک استراتژی سودده تضمین‌شده نیست — نقطه شروع است تا چیزی داشته
باشی که بتوانی اندازه‌گیری و بهترش کنی.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..indicators import atr, crossover, crossunder, ema
from .base import Strategy


class EmaTrendStrategy(Strategy):
    name = "ema_trend"

    @staticmethod
    def defaults() -> dict[str, Any]:
        return {
            "ema_fast": 12,
            "ema_slow": 26,
            "ema_trend": 200,
            "atr_period": 14,
            "atr_stop_mult": 2.5,
            "atr_target_mult": 5.0,
        }

    @property
    def warmup(self) -> int:
        return int(max(self.params["ema_trend"], self.params["atr_period"])) + 5

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        close = df["close"]

        fast = ema(close, p["ema_fast"])
        slow = ema(close, p["ema_slow"])
        trend = ema(close, p["ema_trend"])
        vol = atr(df, p["atr_period"])

        uptrend = close > trend
        entry = crossover(fast, slow) & uptrend
        exit_ = crossunder(fast, slow)

        out = pd.DataFrame(index=df.index)
        out["entry"] = entry.fillna(False)
        out["exit"] = exit_.fillna(False)
        out["stop_distance"] = vol * p["atr_stop_mult"]
        out["target_distance"] = vol * p["atr_target_mult"]

        # در دوره گرم شدن اندیکاتورها هیچ معامله‌ای نمی‌کنیم.
        out.iloc[: self.warmup, out.columns.get_loc("entry")] = False
        out.iloc[: self.warmup, out.columns.get_loc("exit")] = False
        return out
