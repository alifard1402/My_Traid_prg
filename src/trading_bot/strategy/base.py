"""رابط مشترک استراتژی‌ها."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

#: ستون‌هایی که خروجی هر استراتژی باید داشته باشد
SIGNAL_COLUMNS = ["entry", "exit", "stop_distance"]


class Strategy(ABC):
    """یک استراتژی معاملاتی.

    قرارداد مهم: سیگنالِ هر کندل فقط با اطلاعاتِ همان کندل و کندل‌های
    قبل‌تر محاسبه می‌شود. موتور بک‌تست هم سیگنالِ کندل قبل را روی
    قیمتِ باز شدنِ کندل بعد اجرا می‌کند. این یعنی هیچ «نگاه به آینده»
    (look-ahead bias) در کار نیست — شایع‌ترین دلیلِ بک‌تست‌های دروغین.
    """

    name: str = "base"

    def __init__(self, **params: Any) -> None:
        self.params = {**self.defaults(), **params}

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
        """

    def __repr__(self) -> str:
        args = ", ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.__class__.__name__}({args})"
