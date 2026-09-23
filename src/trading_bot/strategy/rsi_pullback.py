"""استراتژی «خرید در اصلاح» (RSI Pullback).

  ورود: روند کلی صعودی باشد (قیمت بالای میانگین بلندمدت) و RSI از زیر
        سطح «اشباع فروش» دوباره به بالا برگردد
        → قیمت در یک روند صعودی موقتاً افت کرده و دارد برمی‌گردد
  خروج: RSI به سطح «اشباع خرید» برسد (قیمت موقتاً زیادی بالا رفته)

منطق: «در روند صعودی، ارزان بخر». برخلاف روندگیری، درصد برد بالاتری دارد
ولی سود هر معامله کوچک‌تر است. خطرش این است که گاهی «اصلاح» در واقع شروع
یک روند نزولی است — حد ضرر برای همین است.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..indicators import atr, ema, rsi
from .base import ATR_PARAMS, Check, Param, Strategy, fmt


class RsiPullbackStrategy(Strategy):
    name = "rsi_pullback"
    title = "خرید در اصلاح قیمت (RSI)"
    description = (
        "وقتی روند کلی طلا صعودی است ولی قیمت موقتاً افت کرده (RSI پایین آمده) و دارد برمی‌گردد، "
        "می‌خرد — یعنی «در روند صعودی، ارزان بخر». وقتی RSI خیلی بالا رفت می‌فروشد. "
        "درصد برد بالاتری دارد ولی سود هر معامله کوچک‌تر است."
    )
    param_info = {
        "rsi_period": Param("دوره RSI (کندل)", "RSI عددی بین ۰ تا ۱۰۰ است که نشان می‌دهد قیمت اخیراً چقدر تند بالا یا پایین رفته.", 2, 50),
        "oversold": Param(
            "سطح اشباع فروش", "وقتی RSI زیر این عدد برود یعنی قیمت زیادی افت کرده. برگشتش از این سطح = سیگنال خرید.",
            5, 50, 1, "float",
        ),
        "overbought": Param(
            "سطح اشباع خرید", "وقتی RSI به این عدد برسد یعنی قیمت زیادی بالا رفته؛ می‌فروشیم.",
            50, 95, 1, "float",
        ),
        "ema_trend": Param("فیلتر روند (کندل)", "فقط وقتی می‌خریم که قیمت بالای این میانگین بلندمدت باشد.", 20, 400),
        **ATR_PARAMS,
    }

    @staticmethod
    def defaults() -> dict[str, Any]:
        return {
            "rsi_period": 14,
            "oversold": 35.0,
            "overbought": 70.0,
            "ema_trend": 200,
            "atr_period": 14,
            "atr_stop_mult": 2.0,
            "atr_target_mult": 4.0,
        }

    @property
    def warmup(self) -> int:
        p = self.params
        return int(max(p["ema_trend"], p["rsi_period"], p["atr_period"])) + 5

    def indicators(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        return {f"روند {self.params['ema_trend']}": ema(df["close"], int(self.params["ema_trend"]))}

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        close = df["close"]
        r = rsi(close, int(p["rsi_period"]))
        trend = ema(close, int(p["ema_trend"]))
        vol = atr(df, p["atr_period"])

        # برگشت از اشباع فروش: کندل قبل زیر سطح، این کندل بالای سطح
        rebound = (r > p["oversold"]) & (r.shift(1) <= p["oversold"])
        entry = rebound & (close > trend)

        out = pd.DataFrame(index=df.index)
        out["entry"] = entry.fillna(False)
        out["exit"] = (r >= p["overbought"]).fillna(False)
        out["stop_distance"] = vol * p["atr_stop_mult"]
        out["target_distance"] = vol * p["atr_target_mult"]
        out.iloc[: self.warmup, out.columns.get_loc("entry")] = False
        out.iloc[: self.warmup, out.columns.get_loc("exit")] = False
        return out

    def explain(self, df: pd.DataFrame) -> list[Check]:
        p = self.params
        close = df["close"]
        price = close.iloc[-1]
        trend = ema(close, int(p["ema_trend"])).iloc[-1]
        r = rsi(close, int(p["rsi_period"])).iloc[-1]

        if r <= p["oversold"]:
            rsi_text, rsi_ok = f"RSI = {r:.0f}: قیمت زیادی افت کرده (اشباع فروش) — منتظر برگشت به بالای {p['oversold']:.0f}", None
        elif r >= p["overbought"]:
            rsi_text, rsi_ok = f"RSI = {r:.0f}: قیمت زیادی بالا رفته (اشباع خرید) — زمان فروش", False
        else:
            rsi_text, rsi_ok = f"RSI = {r:.0f}: وضعیت عادی — منتظر افت به زیر {p['oversold']:.0f}", None

        return [
            Check(
                f"روند کلی {'صعودی' if price > trend else 'نزولی'} است: قیمت {fmt(price)} و میانگین {p['ema_trend']} = {fmt(trend)}",
                bool(price > trend),
            ),
            Check(rsi_text, rsi_ok),
        ]
