"""موتور بک‌تست — استراتژی را روی داده گذشته، کندل به کندل، اجرا می‌کند.

اصول رعایت‌شده (که اکثر بک‌تست‌های اینترنتی رعایت نمی‌کنند):

  ۱. بدون نگاه به آینده: سیگنالِ کندلِ i روی قیمتِ *باز شدنِ* کندل i+1
     اجرا می‌شود. در لحظه بسته شدن کندل i، قیمتِ آن کندل را نمی‌دانستیم.
  ۲. کارمزد و لغزش قیمت در هر دو طرف معامله کسر می‌شود.
  ۳. اگر در یک کندل هم حد ضرر و هم حد سود در دسترس باشد، فرض می‌کنیم
     حد ضرر اول خورده — محافظه‌کارانه‌ترین فرض ممکن.
  ۴. فقط پوزیشن خرید (Long) و بدون اهرم — مثل خرید نقدی در صرافی.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..risk import RiskManager
from ..strategy.base import Strategy
from . import metrics as metrics_mod


@dataclass
class Trade:
    """یک معامله کامل، از ورود تا خروج."""

    entry_time: pd.Timestamp
    entry_price: float
    quantity: float
    stop_price: float
    target_price: float
    exit_time: pd.Timestamp | None = None
    exit_price: float = 0.0
    exit_reason: str = ""
    fees: float = 0.0
    bars_held: int = 0

    @property
    def pnl(self) -> float:
        """سود/زیان خالص، بعد از کسر کارمزد."""
        if self.exit_time is None:
            return 0.0
        return (self.exit_price - self.entry_price) * self.quantity - self.fees

    @property
    def pnl_pct(self) -> float:
        cost = self.entry_price * self.quantity
        return self.pnl / cost * 100 if cost else 0.0


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: list[Trade]
    metrics: metrics_mod.Metrics
    signals: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)
    stopped_early: bool = False

    def trades_frame(self) -> pd.DataFrame:
        """معاملات را به صورت جدول برمی‌گرداند."""
        if not self.trades:
            return pd.DataFrame(
                columns=["entry_time", "exit_time", "entry_price", "exit_price",
                         "quantity", "pnl", "pnl_pct", "exit_reason", "bars_held"]
            )
        return pd.DataFrame(
            [
                {
                    "entry_time": t.entry_time,
                    "exit_time": t.exit_time,
                    "entry_price": round(t.entry_price, 2),
                    "exit_price": round(t.exit_price, 2),
                    "quantity": round(t.quantity, 8),
                    "pnl": round(t.pnl, 2),
                    "pnl_pct": round(t.pnl_pct, 2),
                    "exit_reason": t.exit_reason,
                    "bars_held": t.bars_held,
                }
                for t in self.trades
            ]
        )


class Backtester:
    def __init__(
        self,
        strategy: Strategy,
        risk: RiskManager,
        initial_capital: float = 1000.0,
        fee_rate: float = 0.001,
        slippage_rate: float = 0.0005,
        timeframe: str = "4h",
    ) -> None:
        self.strategy = strategy
        self.risk = risk
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        self.timeframe = timeframe

    # ---- کمک‌کننده‌های هزینه ----

    def _buy_price(self, price: float) -> float:
        """قیمت واقعی خرید: کمی بدتر از قیمت روی تابلو."""
        return price * (1 + self.slippage_rate)

    def _sell_price(self, price: float) -> float:
        return price * (1 - self.slippage_rate)

    def _fee(self, notional: float) -> float:
        return abs(notional) * self.fee_rate

    # ---- حلقه اصلی ----

    def run(self, df: pd.DataFrame) -> BacktestResult:
        if len(df) <= self.strategy.warmup + 2:
            raise ValueError(
                f"داده کافی نیست: {len(df)} کندل داری، "
                f"استراتژی حداقل {self.strategy.warmup + 3} کندل لازم دارد."
            )

        signals = self.strategy.generate(df)

        cash = self.initial_capital
        equity = self.initial_capital
        peak_equity = self.initial_capital
        open_trade: Trade | None = None
        trades: list[Trade] = []
        equity_points: list[float] = []
        stopped_early = False

        opens = df["open"].to_numpy()
        highs = df["high"].to_numpy()
        lows = df["low"].to_numpy()
        closes = df["close"].to_numpy()
        index = df.index

        entries = signals["entry"].to_numpy()
        exits = signals["exit"].to_numpy()
        stop_dist = signals["stop_distance"].to_numpy()
        target_dist = signals["target_distance"].to_numpy()

        for i in range(1, len(df)):
            bar_open, bar_high, bar_low, bar_close = opens[i], highs[i], lows[i], closes[i]
            now = index[i]

            # ── ۱) مدیریت پوزیشن باز: اول حد ضرر، بعد حد سود، بعد سیگنال خروج
            if open_trade is not None:
                open_trade.bars_held += 1
                exit_price = None
                reason = ""

                if bar_low <= open_trade.stop_price:
                    # فرض محافظه‌کارانه: اگر کندل با گپ زیر حد ضرر باز شود،
                    # با قیمتِ بازِ بدترْ خارج می‌شویم، نه با قیمت حد ضرر.
                    exit_price = min(open_trade.stop_price, bar_open)
                    reason = "stop_loss"
                elif bar_high >= open_trade.target_price:
                    exit_price = max(open_trade.target_price, bar_open)
                    reason = "take_profit"
                elif exits[i - 1]:
                    exit_price = bar_open
                    reason = "signal"

                if exit_price is not None:
                    fill = self._sell_price(exit_price)
                    proceeds = fill * open_trade.quantity
                    fee = self._fee(proceeds)

                    cash += proceeds - fee
                    open_trade.exit_time = now
                    open_trade.exit_price = fill
                    open_trade.exit_reason = reason
                    open_trade.fees += fee
                    trades.append(open_trade)
                    open_trade = None

            # ── ۲) ورود جدید (فقط وقتی پوزیشن باز نداریم)
            if open_trade is None and entries[i - 1] and not stopped_early:
                fill = self._buy_price(bar_open)
                plan = self.risk.plan(
                    equity=cash,
                    entry_price=fill,
                    stop_distance=float(stop_dist[i - 1]),
                    target_distance=float(target_dist[i - 1]),
                )
                cost = plan.notional
                fee = self._fee(cost)
                if plan.is_valid and cost + fee <= cash:
                    cash -= cost + fee
                    open_trade = Trade(
                        entry_time=now,
                        entry_price=fill,
                        quantity=plan.quantity,
                        stop_price=plan.stop_price,
                        target_price=plan.target_price,
                        fees=fee,
                    )

            # ── ۳) ارزش‌گذاری سرمایه در پایان کندل
            position_value = open_trade.quantity * bar_close if open_trade else 0.0
            equity = cash + position_value
            equity_points.append(equity)
            peak_equity = max(peak_equity, equity)

            # ── ۴) کلید قطع اضطراری: افت سرمایه از حد مجاز رد شد
            if not stopped_early and self.risk.breached_max_drawdown(equity, peak_equity):
                stopped_early = True
                if open_trade is not None:
                    fill = self._sell_price(bar_close)
                    proceeds = fill * open_trade.quantity
                    fee = self._fee(proceeds)
                    cash += proceeds - fee
                    open_trade.exit_time = now
                    open_trade.exit_price = fill
                    open_trade.exit_reason = "max_drawdown"
                    open_trade.fees += fee
                    trades.append(open_trade)
                    open_trade = None
                    equity_points[-1] = cash

        # پوزیشنِ بازِ آخر را با قیمت پایانی می‌بندیم تا نتیجه کامل باشد.
        if open_trade is not None:
            fill = self._sell_price(closes[-1])
            proceeds = fill * open_trade.quantity
            fee = self._fee(proceeds)
            cash += proceeds - fee
            open_trade.exit_time = index[-1]
            open_trade.exit_price = fill
            open_trade.exit_reason = "end_of_data"
            open_trade.fees += fee
            trades.append(open_trade)
            equity_points[-1] = cash

        equity_curve = pd.Series(equity_points, index=index[1:], name="equity")

        return BacktestResult(
            equity_curve=equity_curve,
            trades=trades,
            metrics=metrics_mod.compute(
                equity_curve, trades, df["close"], self.initial_capital, self.timeframe
            ),
            signals=signals,
            stopped_early=stopped_early,
        )
