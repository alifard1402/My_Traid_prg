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

طلا بازاری است که روندهای طولانی دارد؛ برای همین روندگیری ساده روی آن
معنادار است. ولی این یک استراتژی سودده تضمین‌شده نیست — نقطه شروع است
تا چیزی داشته باشی که بتوانی اندازه‌گیری و بهترش کنی.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..indicators import atr, crossover, crossunder, ema
from .base import ATR_PARAMS, Check, Param, Strategy, fmt


class EmaTrendStrategy(Strategy):
    name = "ema_trend"
    title = "دنبال‌کردن روند (میانگین متحرک)"
    description = (
        "وقتی روند کلی طلا صعودی است (قیمت بالای میانگین بلندمدت)، منتظر می‌ماند تا "
        "میانگین کوتاه‌مدت از میانگین میان‌مدت بالا بزند — یعنی حرکت صعودی تازه‌ای شروع شده — "
        "و می‌خرد. وقتی میانگین کوتاه‌مدت دوباره پایین آمد، می‌فروشد. "
        "مناسب بازارهایی که روندهای طولانی دارند؛ در بازار بی‌جهت چند ضرر کوچک پشت‌سرهم می‌دهد."
    )
    param_info = {
        "ema_fast": Param("میانگین سریع (کندل)", "میانگین قیمت چند کندل آخر؛ سریع به تغییرات واکنش می‌دهد.", 3, 100),
        "ema_slow": Param("میانگین کند (کندل)", "میانگین طولانی‌تر. عبور میانگین سریع از این، سیگنال خرید/فروش است.", 5, 300),
        "ema_trend": Param(
            "فیلتر روند (کندل)",
            "فقط وقتی می‌خریم که قیمت بالای این میانگین بلندمدت باشد، یعنی روند کلی صعودی است.",
            20, 400,
        ),
        **ATR_PARAMS,
    }

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

    def indicators(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        p = self.params
        close = df["close"]
        return {
            f"میانگین {p['ema_fast']}": ema(close, p["ema_fast"]),
            f"میانگین {p['ema_slow']}": ema(close, p["ema_slow"]),
            f"روند {p['ema_trend']}": ema(close, p["ema_trend"]),
        }

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

    def explain(self, df: pd.DataFrame) -> list[Check]:
        p = self.params
        close = df["close"]
        fast = ema(close, p["ema_fast"]).iloc[-1]
        slow = ema(close, p["ema_slow"]).iloc[-1]
        trend = ema(close, p["ema_trend"]).iloc[-1]
        price = close.iloc[-1]
        signals = self.generate(df)

        checks = [
            Check(
                f"روند کلی صعودی است: قیمت ({fmt(price)}) بالای میانگین {p['ema_trend']} ({fmt(trend)})"
                if price > trend else
                f"روند کلی نزولی است: قیمت ({fmt(price)}) زیر میانگین {p['ema_trend']} ({fmt(trend)}) — خرید نمی‌کنیم",
                bool(price > trend),
            ),
            Check(
                f"میانگین سریع ({fmt(fast)}) بالای میانگین کند ({fmt(slow)}) است — حرکت کوتاه‌مدت صعودی"
                if fast > slow else
                f"میانگین سریع ({fmt(fast)}) زیر میانگین کند ({fmt(slow)}) است — منتظر عبور به بالا",
                bool(fast > slow),
            ),
        ]
        if bool(signals["entry"].iloc[-1]):
            checks.append(Check("همین الان سیگنال خرید صادر شد ✦", True))
        elif bool(signals["exit"].iloc[-1]):
            checks.append(Check("همین الان سیگنال خروج صادر شد", False))
        return checks
