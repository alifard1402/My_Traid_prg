"""رابط مشترک بروکر (جایی که سفارش‌ها اجرا می‌شوند)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Order:
    side: str          # "buy" یا "sell"
    symbol: str
    quantity: float
    price: float
    fee: float = 0.0
    timestamp: str = ""


class Broker(ABC):
    """هر چیزی که بتواند سفارش اجرا کند: شبیه‌ساز یا صرافی واقعی."""

    name: str = "base"

    @abstractmethod
    def buy(self, symbol: str, quantity: float, price: float) -> Order: ...

    @abstractmethod
    def sell(self, symbol: str, quantity: float, price: float) -> Order: ...

    @abstractmethod
    def equity(self, mark_price: float) -> float:
        """ارزش کل حساب با قیمت فعلی بازار."""
