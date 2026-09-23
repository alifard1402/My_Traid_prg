"""بروکر کاغذی — معامله با پول تقلبی.

سفارش واقعی به هیچ صرافی‌ای ارسال نمی‌شود. همه‌چیز در یک فایل JSON
ذخیره می‌شود تا با خاموش و روشن شدن ربات، وضعیت حساب گم نشود.

این جایی است که باید ماه‌ها بمانی، نه چند روز.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .base import Broker, Order


@dataclass
class PaperState:
    cash: float
    position_qty: float = 0.0
    position_entry: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0
    realized_pnl: float = 0.0
    total_fees: float = 0.0
    orders: list[dict] = field(default_factory=list)
    #: معاملات کامل‌شده (ورود تا خروج) برای گزارش و پنل
    trades: list[dict] = field(default_factory=list)
    position_time: str = ""       # زمان باز شدن پوزیشن فعلی
    position_fee: float = 0.0     # کارمزد خرید پوزیشن فعلی (در سود/زیان معامله حساب می‌شود)
    peak_equity: float = 0.0      # بالاترین ارزش حساب تا حالا (برای کلید قطع اضطراری)
    last_signal_bar: str = ""     # زمان آخرین کندلی که سیگنالش را اجرا کردیم
    halted: bool = False          # کلید قطع اضطراری زده شده؟
    #: ارزش حساب در پایان هر کندل: [[زمان, ارزش], ...] برای نمودار منحنی سرمایه
    equity_history: list[list] = field(default_factory=list)

    @property
    def in_position(self) -> bool:
        return self.position_qty > 0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PaperBroker(Broker):
    name = "paper"

    def __init__(
        self,
        initial_capital: float = 1000.0,
        fee_rate: float = 0.001,
        slippage_rate: float = 0.0005,
        state_file: str | Path = "data/paper_state.json",
    ) -> None:
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        self.state_file = Path(state_file)
        self.state = self._load(initial_capital)

    # ---- ذخیره و بازیابی وضعیت ----

    def _load(self, initial_capital: float) -> PaperState:
        if self.state_file.exists():
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
            known = PaperState.__dataclass_fields__
            return PaperState(**{k: v for k, v in raw.items() if k in known})
        return PaperState(cash=initial_capital, peak_equity=initial_capital)

    def save(self) -> None:
        """ذخیره اتمیک: اول در فایل موقت، بعد جابه‌جایی.

        اگر وسط نوشتن برق برود یا سرور ری‌استارت شود، فایل وضعیت نصفه نمی‌ماند.
        """
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self.state), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.state_file)

    def reset(self, initial_capital: float) -> None:
        self.state = PaperState(cash=initial_capital, peak_equity=initial_capital)
        self.save()

    # ---- اجرای سفارش ----

    def buy(self, symbol: str, quantity: float, price: float, reason: str = "") -> Order:
        fill = price * (1 + self.slippage_rate)
        cost = fill * quantity
        fee = cost * self.fee_rate
        if cost + fee > self.state.cash:
            raise ValueError(
                f"موجودی کافی نیست: نیاز {cost + fee:.2f}، موجود {self.state.cash:.2f}"
            )

        self.state.cash -= cost + fee
        self.state.position_qty += quantity
        self.state.position_entry = fill
        self.state.position_fee += fee
        self.state.position_time = now_iso()
        self.state.total_fees += fee
        return self._record("buy", symbol, quantity, fill, fee, reason)

    def sell(self, symbol: str, quantity: float, price: float, reason: str = "") -> Order:
        quantity = min(quantity, self.state.position_qty)
        if quantity <= 0:
            raise ValueError("پوزیشنی برای فروش وجود ندارد.")

        fill = price * (1 - self.slippage_rate)
        proceeds = fill * quantity
        fee = proceeds * self.fee_rate

        s = self.state
        # کارمزد خرید را به نسبتِ حجم فروخته‌شده به حساب همین فروش می‌گذاریم.
        entry_fee = s.position_fee * (quantity / s.position_qty)
        pnl = (fill - s.position_entry) * quantity - fee - entry_fee

        s.cash += proceeds - fee
        s.realized_pnl += pnl
        s.position_fee -= entry_fee
        s.position_qty -= quantity
        s.total_fees += fee
        s.trades.append({
            "entry_time": s.position_time,
            "exit_time": now_iso(),
            "entry_price": s.position_entry,
            "exit_price": fill,
            "quantity": quantity,
            "pnl": pnl,
            "pnl_pct": pnl / (s.position_entry * quantity) * 100 if s.position_entry else 0.0,
            "exit_reason": reason,
        })
        if s.position_qty <= 1e-12:
            s.position_qty = 0.0
            s.position_entry = 0.0
            s.position_fee = 0.0
            s.position_time = ""
            s.stop_price = 0.0
            s.target_price = 0.0
        return self._record("sell", symbol, quantity, fill, fee, reason)

    def _record(
        self, side: str, symbol: str, qty: float, price: float, fee: float, reason: str = ""
    ) -> Order:
        order = Order(
            side=side, symbol=symbol, quantity=qty, price=price, fee=fee,
            timestamp=now_iso(), reason=reason,
        )
        self.state.orders.append(asdict(order))
        self.save()
        return order

    def equity(self, mark_price: float) -> float:
        return self.state.cash + self.state.position_qty * mark_price
