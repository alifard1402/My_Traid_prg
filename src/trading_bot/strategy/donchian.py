"""استراتژی «شکست کانال» (Donchian Breakout) — سبک معروف لاک‌پشت‌ها.

  ورود: قیمت بسته شدن از بالاترین قیمتِ N کندل قبل بالاتر برود
        (یعنی طلا سقف تازه زده و احتمالاً روند صعودی قوی شروع شده)
  خروج: قیمت بسته شدن از پایین‌ترین قیمتِ M کندل قبل پایین‌تر برود

در دهه ۱۹۸۰ گروهی به اسم «لاک‌پشت‌ها» با همین قانون ساده روی کالاهایی
مثل طلا معامله می‌کردند. ایده: روندهای بزرگ همیشه با شکستن سقف شروع
می‌شوند. عیبش: شکست‌های دروغین زیاد است، پس درصد برد پایین است و سود
از چند روند بزرگ می‌آید.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..indicators import atr, ema
from .base import ATR_PARAMS, Check, Param, Strategy, fmt


class DonchianBreakoutStrategy(Strategy):
    name = "donchian_breakout"
    title = "شکست سقف (کانال دونچیان)"
    description = (
        "وقتی قیمت طلا از بالاترین قیمتِ چند هفته اخیر بالاتر رفت (سقف را شکست) می‌خرد، "
        "به این امید که روند صعودی قوی شروع شده. وقتی قیمت از کفِ کانال پایین‌تر رفت می‌فروشد. "
        "درصد برد پایینی دارد (شکست‌های دروغین زیادند) ولی در روندهای بزرگ سود خوبی می‌گیرد."
    )
    param_info = {
        "entry_period": Param(
            "دوره سقف (کندل)", "قیمت باید از بالاترین قیمتِ این تعداد کندل آخر بالاتر برود تا بخریم.", 5, 200,
        ),
        "exit_period": Param(
            "دوره کف (کندل)", "اگر قیمت از پایین‌ترین قیمتِ این تعداد کندل آخر پایین‌تر برود، می‌فروشیم.", 3, 200,
        ),
        "trend_filter": Param(
            "فیلتر روند (کندل)",
            "فقط وقتی می‌خریم که قیمت بالای این میانگین بلندمدت باشد. ۰ یعنی فیلتر خاموش.",
            0, 400,
        ),
        **ATR_PARAMS,
    }

    @staticmethod
    def defaults() -> dict[str, Any]:
        return {
            "entry_period": 55,
            "exit_period": 20,
            "trend_filter": 0,
            "atr_period": 20,
            "atr_stop_mult": 2.0,
            "atr_target_mult": 8.0,
        }

    @property
    def warmup(self) -> int:
        p = self.params
        return int(max(p["entry_period"], p["exit_period"], p["trend_filter"], p["atr_period"])) + 5

    def _channel(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        # shift(1): سقف/کفِ کندل‌های *قبلی* — کندل فعلی نباید با خودش مقایسه شود.
        upper = df["high"].rolling(int(self.params["entry_period"])).max().shift(1)
        lower = df["low"].rolling(int(self.params["exit_period"])).min().shift(1)
        return upper, lower

    def indicators(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        upper, lower = self._channel(df)
        lines = {"سقف کانال": upper, "کف کانال": lower}
        if self.params["trend_filter"]:
            lines[f"روند {self.params['trend_filter']}"] = ema(df["close"], int(self.params["trend_filter"]))
        return lines

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        close = df["close"]
        upper, lower = self._channel(df)
        vol = atr(df, p["atr_period"])

        entry = close > upper
        if p["trend_filter"]:
            entry &= close > ema(close, int(p["trend_filter"]))

        out = pd.DataFrame(index=df.index)
        out["entry"] = entry.fillna(False)
        out["exit"] = (close < lower).fillna(False)
        out["stop_distance"] = vol * p["atr_stop_mult"]
        out["target_distance"] = vol * p["atr_target_mult"]
        out.iloc[: self.warmup, out.columns.get_loc("entry")] = False
        out.iloc[: self.warmup, out.columns.get_loc("exit")] = False
        return out

    def explain(self, df: pd.DataFrame) -> list[Check]:
        upper, lower = self._channel(df)
        price, up, low = df["close"].iloc[-1], upper.iloc[-1], lower.iloc[-1]
        gap_pct = (up / price - 1) * 100
        checks = [
            Check(
                f"قیمت ({fmt(price)}) سقف {self.params['entry_period']} کندل اخیر ({fmt(up)}) را شکسته"
                if price > up else
                f"قیمت ({fmt(price)}) هنوز {gap_pct:.2f}٪ با سقف کانال ({fmt(up)}) فاصله دارد",
                bool(price > up),
            ),
            Check(
                f"کف کانال خروج: {fmt(low)} — اگر قیمت زیر این برود، می‌فروشیم",
                bool(price >= low),
            ),
        ]
        if self.params["trend_filter"]:
            trend = ema(df["close"], int(self.params["trend_filter"])).iloc[-1]
            checks.insert(0, Check(
                f"فیلتر روند: قیمت {'بالای' if price > trend else 'زیر'} میانگین {self.params['trend_filter']} ({fmt(trend)})",
                bool(price > trend),
            ))
        return checks
