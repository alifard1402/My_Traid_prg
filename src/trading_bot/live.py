"""حلقه معامله زنده (فعلاً فقط حالت کاغذی).

هر چند ثانیه یک بار:
   کندل‌ها را می‌گیرد → سیگنال می‌سازد → حد ضرر/سود را چک می‌کند →
   در صورت لزوم سفارش کاغذی می‌زند → وضعیت را ذخیره می‌کند

نکته مهم: سیگنال فقط از روی *آخرین کندلِ بسته‌شده* خوانده می‌شود.
کندلِ در حالِ شکل‌گیری هنوز تمام نشده و قیمتش تا لحظه بسته شدن عوض
می‌شود؛ تصمیم‌گیری بر اساس آن، ربات را دچار سیگنال‌های ناپایدار می‌کند.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from .broker import PaperBroker
from .config import Config
from .data import load_ohlcv
from .risk import RiskManager
from .strategy import get_strategy

log = logging.getLogger("trading_bot.live")


class LiveTrader:
    def __init__(self, cfg: Config) -> None:
        if cfg.live.mode != "paper":
            raise NotImplementedError(
                "فقط حالت paper (پول تقلبی) پیاده‌سازی شده است.\n"
                "اتصال به حساب واقعی عمداً پیاده‌سازی نشده — تا وقتی چند ماه\n"
                "نتیجه حالت کاغذی را ندیده‌ای، نباید پول واقعی وارد کنی."
            )
        self.cfg = cfg
        self.strategy = get_strategy(cfg.strategy.name, **cfg.strategy.params)
        self.risk = RiskManager(
            risk_per_trade=cfg.risk.risk_per_trade,
            max_position_pct=cfg.risk.max_position_pct,
            max_drawdown_stop=cfg.risk.max_drawdown_stop,
        )
        self.broker = PaperBroker(
            initial_capital=cfg.risk.initial_capital,
            fee_rate=cfg.costs.fee_rate,
            slippage_rate=cfg.costs.slippage_rate,
            state_file=cfg.live.state_file,
        )
        self.peak_equity = max(
            cfg.risk.initial_capital, self.broker.equity(self.broker.state.position_entry or 1)
        )

    def step(self) -> None:
        """یک دور از حلقه — گرفتن داده، تصمیم، اجرا."""
        m = self.cfg.market
        df = load_ohlcv(m.source, m.symbol, m.timeframe, limit=self.strategy.warmup + 60)
        signals = self.strategy.generate(df)

        # آخرین کندلِ بسته‌شده = یکی مانده به آخر (آخری هنوز در حال شکل‌گیری است)
        closed = -2
        price = float(df["close"].iloc[-1])
        state = self.broker.state
        equity = self.broker.equity(price)
        self.peak_equity = max(self.peak_equity, equity)

        # کلید قطع اضطراری
        if self.risk.breached_max_drawdown(equity, self.peak_equity):
            if state.in_position:
                self.broker.sell(m.symbol, state.position_qty, price)
            log.error(
                "افت سرمایه از حد مجاز (%.0f%%) رد شد. ربات متوقف شد.",
                self.cfg.risk.max_drawdown_stop * 100,
            )
            raise SystemExit(1)

        if state.in_position:
            if price <= state.stop_price:
                order = self.broker.sell(m.symbol, state.position_qty, price)
                log.warning("حد ضرر خورد → فروش %.8f در %.2f", order.quantity, order.price)
            elif price >= state.target_price:
                order = self.broker.sell(m.symbol, state.position_qty, price)
                log.info("حد سود خورد → فروش %.8f در %.2f", order.quantity, order.price)
            elif bool(signals["exit"].iloc[closed]):
                order = self.broker.sell(m.symbol, state.position_qty, price)
                log.info("سیگنال خروج → فروش %.8f در %.2f", order.quantity, order.price)
            else:
                log.info(
                    "در پوزیشن | قیمت %.2f | حد ضرر %.2f | حد سود %.2f | سرمایه %.2f",
                    price, state.stop_price, state.target_price, equity,
                )
        elif bool(signals["entry"].iloc[closed]):
            plan = self.risk.plan(
                equity=state.cash,
                entry_price=price,
                stop_distance=float(signals["stop_distance"].iloc[closed]),
                target_distance=float(signals["target_distance"].iloc[closed]),
            )
            if plan.is_valid:
                order = self.broker.buy(m.symbol, plan.quantity, price)
                state.stop_price = plan.stop_price
                state.target_price = plan.target_price
                self.broker.save()
                log.info(
                    "سیگنال ورود → خرید %.8f در %.2f | حد ضرر %.2f | حد سود %.2f",
                    order.quantity, order.price, plan.stop_price, plan.target_price,
                )
            else:
                log.info("سیگنال ورود آمد ولی حجم محاسبه‌شده معتبر نبود؛ رد شد.")
        else:
            log.info("بدون سیگنال | قیمت %.2f | نقد %.2f", price, state.cash)

    def run(self, max_iterations: int | None = None) -> None:
        log.info(
            "شروع ربات (حالت کاغذی) | %s %s از %s | سرمایه %.2f",
            self.cfg.market.symbol, self.cfg.market.timeframe,
            self.cfg.market.source, self.broker.state.cash,
        )
        iteration = 0
        while max_iterations is None or iteration < max_iterations:
            try:
                self.step()
            except SystemExit:
                raise
            except Exception as exc:  # یک خطای موقت شبکه نباید ربات را بکشد
                log.error("خطا در این دور (ادامه می‌دهیم): %s", exc)

            iteration += 1
            if max_iterations is not None and iteration >= max_iterations:
                break
            time.sleep(self.cfg.live.poll_seconds)

    def summary(self, price: float) -> str:
        s = self.broker.state
        return (
            f"وضعیت حساب کاغذی @ {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n"
            f"  نقد          : {s.cash:,.2f}\n"
            f"  حجم پوزیشن   : {s.position_qty:.8f}\n"
            f"  سود/زیان محقق: {s.realized_pnl:,.2f}\n"
            f"  کارمزد کل    : {s.total_fees:,.2f}\n"
            f"  ارزش کل حساب : {self.broker.equity(price):,.2f}\n"
            f"  تعداد سفارش  : {len(s.orders)}"
        )
