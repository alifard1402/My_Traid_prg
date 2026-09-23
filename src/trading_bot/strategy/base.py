"""رابط مشترک استراتژی‌ها."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

#: ستون‌هایی که خروجی هر استراتژی باید داشته باشد
SIGNAL_COLUMNS = ["entry", "exit", "stop_distance", "target_distance"]


@dataclass(frozen=True)
class Param:
    """توضیح یک پارامتر برای نمایش در پنل — به زبان ساده."""

    label: str
    help: str
    min: float
    max: float
    step: float = 1
    kind: str = "int"  # int | float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Check:
    """یک جمله از «ربات الان چه فکر می‌کند؟».

    ok=True یعنی این شرط برقرار است، False یعنی نیست، None یعنی فقط اطلاعات.
    """

    text: str
    ok: bool | None = None


class Strategy(ABC):
    """یک استراتژی معاملاتی.

    قرارداد مهم: سیگنالِ هر کندل فقط با اطلاعاتِ همان کندل و کندل‌های
    قبل‌تر محاسبه می‌شود. موتور بک‌تست هم سیگنالِ کندل قبل را روی
    قیمتِ باز شدنِ کندل بعد اجرا می‌کند. این یعنی هیچ «نگاه به آینده»
    (look-ahead bias) در کار نیست — شایع‌ترین دلیلِ بک‌تست‌های دروغین.
    """

    name: str = "base"
    #: نام فارسی برای پنل
    title: str = ""
    #: توضیح یک‌پاراگرافی به زبان ساده
    description: str = ""
    #: توضیح هر پارامتر (کلیدها همان کلیدهای defaults)
    param_info: dict[str, Param] = {}

    def __init__(self, **params: Any) -> None:
        defaults = self.defaults()
        # پارامترهای ناشناخته (مثلاً از استراتژی قبلی) نادیده گرفته می‌شوند.
        known = {k: v for k, v in params.items() if not defaults or k in defaults}
        # پنل همه اعداد را اعشاری می‌فرستد؛ پارامترهای صحیح (مثل دوره‌ها) صحیح بمانند.
        for k, v in known.items():
            if isinstance(defaults.get(k), int) and isinstance(v, float) and v.is_integer():
                known[k] = int(v)
        self.params = {**defaults, **known}

    @staticmethod
    def defaults() -> dict[str, Any]:
        return {}

    @property
    @abstractmethod
    def warmup(self) -> int:
        """تعداد کندلی که اندیکاتورها برای گرم شدن لازم دارند."""

    @abstractmethod
    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        """از روی کندل‌ها سیگنال می‌سازد.

        خروجی: DataFrame هم‌ایندکس با ورودی، شامل:
          - entry (bool): این کندل سیگنال خرید داد
          - exit (bool): این کندل سیگنال خروج داد
          - stop_distance (float): فاصله حد ضرر از قیمت ورود (به واحد قیمت)
          - target_distance (float): فاصله حد سود از قیمت ورود
        """

    def indicators(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        """خط‌هایی که باید روی نمودار قیمت کشیده شوند: {نام فارسی: سری}."""
        return {}

    def explain(self, df: pd.DataFrame) -> list[Check]:
        """وضعیت فعلی بازار از دید این استراتژی، به زبان ساده.

        df باید فقط شامل کندل‌های *بسته‌شده* باشد.
        """
        return []

    @classmethod
    def describe(cls) -> dict[str, Any]:
        return {
            "name": cls.name,
            "title": cls.title or cls.name,
            "description": cls.description,
            "defaults": cls.defaults(),
            "params": {k: p.as_dict() for k, p in cls.param_info.items()},
        }

    def __repr__(self) -> str:
        args = ", ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.__class__.__name__}({args})"


#: پارامترهای مشترک حد ضرر/سود بر پایه ATR — همه استراتژی‌ها از این استفاده می‌کنند
ATR_PARAMS = {
    "atr_period": Param(
        "دوره ATR", "ATR میانگین «اندازه حرکت» هر کندل است. این عدد می‌گوید میانگینِ چند کندل آخر گرفته شود.",
        5, 50,
    ),
    "atr_stop_mult": Param(
        "فاصله حد ضرر (× ATR)",
        "حد ضرر چند برابر ATR زیر قیمت خرید باشد. عدد کوچک = حد ضرر نزدیک و زود خوردن؛ "
        "عدد بزرگ = حد ضرر دور ولی حجم معامله کمتر (چون ریسک ثابت است).",
        0.5, 6, 0.1, "float",
    ),
    "atr_target_mult": Param(
        "فاصله حد سود (× ATR)",
        "حد سود چند برابر ATR بالای قیمت خرید باشد. معمولاً حداقل ۲ برابر حد ضرر می‌گذارند "
        "تا سود هر برد، ضرر دو باخت را جبران کند.",
        0.5, 20, 0.1, "float",
    ),
}


def fmt(x: float) -> str:
    return f"{x:,.2f}"
