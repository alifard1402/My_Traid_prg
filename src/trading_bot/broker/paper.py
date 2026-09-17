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

    @property
    def in_position(self) -> bool:
        return self.position_qty > 0


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
            return PaperState(**raw)
        return PaperState(cash=initial_capital)

    def save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps(asdict(self.state), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def reset(self, initial_capital: float) -> None:
        self.state = PaperState(cash=initial_capital)
        self.save()

    # ---- اجرای سفارش ----

    def buy(self, symbol: str, quantity: float, price: float) -> Order:
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
        self.state.total_fees += fee
        return self._record("buy", symbol, quantity, fill, fee)

    def sell(self, symbol: str, quantity: float, price: float) -> Order:
        quantity = min(quantity, self.state.position_qty)
        if quantity <= 0:
            raise ValueError("پوزیشنی برای فروش وجود ندارد.")

        fill = price * (1 - self.slippage_rate)
        proceeds = fill * quantity
        fee = proceeds * self.fee_rate

        self.state.cash += proceeds - fee
        self.state.realized_pnl += (fill - self.state.position_entry) * quantity - fee
        self.state.position_qty -= quantity
        self.state.total_fees += fee
        if self.state.position_qty <= 1e-12:
            self.state.position_qty = 0.0
            self.state.position_entry = 0.0
            self.state.stop_price = 0.0
            self.state.target_price = 0.0
        return self._record("sell", symbol, quantity, fill, fee)

    def _record(self, side: str, symbol: str, qty: float, price: float, fee: float) -> Order:
        order = Order(
            side=side,
            symbol=symbol,
            quantity=qty,
            price=price,
            fee=fee,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self.state.orders.append(asdict(order))
        self.save()
        return order

    def equity(self, mark_price: float) -> float:
        return self.state.cash + self.state.position_qty * mark_price
