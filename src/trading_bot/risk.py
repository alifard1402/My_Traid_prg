"""مدیریت ریسک — مهم‌ترین بخش ربات.

استراتژی تعیین می‌کند «کِی» معامله کنیم؛ مدیریت ریسک تعیین می‌کند «چقدر».
یک استراتژی متوسط با مدیریت ریسک خوب زنده می‌ماند؛ یک استراتژی عالی با
مدیریت ریسک بد، ورشکست می‌شود.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PositionPlan:
    """نقشه یک معامله، قبل از باز کردنش."""

    quantity: float
    entry_price: float
    stop_price: float
    target_price: float
    risk_amount: float  # مقدار پولی که اگر حد ضرر بخورد از دست می‌رود

    @property
    def notional(self) -> float:
        return self.quantity * self.entry_price

    @property
    def is_valid(self) -> bool:
        return self.quantity > 0 and self.stop_price < self.entry_price


class RiskManager:
    """اندازه پوزیشن و حد ضرر را حساب می‌کند."""

    def __init__(
        self,
        risk_per_trade: float = 0.01,
        max_position_pct: float = 0.95,
        max_drawdown_stop: float = 0.25,
    ) -> None:
        self.risk_per_trade = risk_per_trade
        self.max_position_pct = max_position_pct
        self.max_drawdown_stop = max_drawdown_stop

    def plan(
        self,
        equity: float,
        entry_price: float,
        stop_distance: float,
        target_distance: float,
    ) -> PositionPlan:
        """حجم معامله را از روی ریسکِ مجاز حساب می‌کند.

        فرمول کلیدی:   حجم = (سرمایه × درصد ریسک) ÷ فاصله حد ضرر

        یعنی حجم را طوری انتخاب می‌کنیم که *اگر* حد ضرر بخورد، دقیقاً
        همان درصدِ از پیش تعیین‌شده را از دست بدهیم — نه بیشتر. برای همین
        در بازار پرنوسان خودبه‌خود حجم کمتری می‌گیریم.
        """
        if equity <= 0 or entry_price <= 0 or stop_distance <= 0:
            return PositionPlan(0.0, entry_price, 0.0, 0.0, 0.0)

        risk_amount = equity * self.risk_per_trade
        quantity = risk_amount / stop_distance

        # سقف حجم: بدون اهرم، و حداکثر درصد مجاز از سرمایه.
        max_quantity = (equity * self.max_position_pct) / entry_price
        quantity = min(quantity, max_quantity)

        return PositionPlan(
            quantity=quantity,
            entry_price=entry_price,
            stop_price=entry_price - stop_distance,
            target_price=entry_price + target_distance,
            risk_amount=quantity * stop_distance,
        )

    def breached_max_drawdown(self, equity: float, peak_equity: float) -> bool:
        """آیا افت سرمایه از حد مجاز رد شده؟ (کلید قطع اضطراری ربات)"""
        if peak_equity <= 0:
            return False
        return (peak_equity - equity) / peak_equity >= self.max_drawdown_stop
