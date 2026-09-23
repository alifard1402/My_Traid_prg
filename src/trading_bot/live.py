"""حلقه معامله زنده (فعلاً فقط حالت کاغذی).

هر چند ثانیه یک بار:
   کندل‌ها را می‌گیرد → سیگنال می‌سازد → حد ضرر/سود را چک می‌کند →
   در صورت لزوم سفارش کاغذی می‌زند → وضعیت را ذخیره می‌کند

دو نکته مهم:

  ۱. سیگنال فقط از روی *آخرین کندلِ بسته‌شده* خوانده می‌شود. کندلِ در
     حالِ شکل‌گیری هنوز تمام نشده و قیمتش تا لحظه بسته شدن عوض می‌شود.

  ۲. سیگنالِ هر کندل فقط *یک بار* اجرا می‌شود. ربات هر ۶۰ ثانیه داده
     می‌گیرد ولی کندل ۴ ساعته فقط هر ۴ ساعت یک بار بسته می‌شود؛ اگر این
     را حواسمان نباشد، بعد از خوردن حد ضرر دوباره با همان سیگنال قدیمی
     می‌خریم.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .broker import PaperBroker
from .config import Config
from .data import AutoSource, load_ohlcv
from .data.base import timeframe_to_minutes
from .risk import RiskManager
from .strategy import get_strategy

log = logging.getLogger("trading_bot.live")


def closed_bars(df: pd.DataFrame, timeframe: str, now: pd.Timestamp | None = None) -> pd.DataFrame:
    """فقط کندل‌هایی که زمانشان کامل تمام شده."""
    now = now or pd.Timestamp.now(tz="UTC")
    bar_length = pd.Timedelta(minutes=timeframe_to_minutes(timeframe))
    return df[df.index + bar_length <= now]


#: حداکثر تعداد نقطه‌های منحنی سرمایه که نگه می‌داریم (~۲ سال کندل ۴ ساعته)
MAX_EQUITY_POINTS = 5000

REASON_TEXT = {
    "signal": "سیگنال استراتژی",
    "stop_loss": "حد ضرر",
    "take_profit": "حد سود",
    "max_drawdown": "کلید قطع اضطراری",
    "manual": "دستی از پنل",
}


class LiveTrader:
    def __init__(self, cfg: Config, stop_event: threading.Event | None = None) -> None:
        if cfg.live.mode != "paper":
            raise NotImplementedError(
                "فقط حالت paper (پول تقلبی) پیاده‌سازی شده است.\n"
                "اتصال به حساب واقعی عمداً پیاده‌سازی نشده — تا وقتی چند ماه\n"
                "نتیجه حالت کاغذی را ندیده‌ای، نباید پول واقعی وارد کنی."
            )
        self.cfg = cfg
        self.stop_event = stop_event or threading.Event()
        self.lock = threading.RLock()
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
        if self.broker.state.peak_equity <= 0:
            self.broker.state.peak_equity = cfg.risk.initial_capital
        #: آخرین وضعیت، برای نمایش در پنل
        self.status: dict[str, Any] = {}

    # ─────────────────────────── یک دور ───────────────────────────

    def step(self, df: pd.DataFrame | None = None, now: pd.Timestamp | None = None) -> dict[str, Any]:
        """یک دور از حلقه — گرفتن داده، تصمیم، اجرا. وضعیت را برمی‌گرداند."""
        m = self.cfg.market
        if df is None:
            df = load_ohlcv(m.source, m.symbol, m.timeframe, limit=self.strategy.warmup + 100)

        with self.lock:
            return self._decide(df, now)

    def _decide(self, df: pd.DataFrame, now: pd.Timestamp | None) -> dict[str, Any]:
        m = self.cfg.market
        state = self.broker.state
        price = float(df["close"].iloc[-1])  # آخرین قیمت (کندل در حال شکل‌گیری)
        done = closed_bars(df, m.timeframe, now)
        if len(done) <= self.strategy.warmup:
            raise ValueError(
                f"داده کافی نیست: {len(done)} کندل بسته‌شده، استراتژی {self.strategy.warmup + 1} لازم دارد."
            )

        signals = self.strategy.generate(done)
        bar_time = done.index[-1].isoformat()
        new_bar = bar_time != state.last_signal_bar
        entry_signal = new_bar and bool(signals["entry"].iloc[-1])
        exit_signal = new_bar and bool(signals["exit"].iloc[-1])

        equity = self.broker.equity(price)
        state.peak_equity = max(state.peak_equity, equity)
        action = "بدون تغییر"

        if state.halted:
            action = "ربات به‌خاطر کلید قطع اضطراری متوقف است — حساب را ریست کن."
        # ── کلید قطع اضطراری
        elif self.risk.breached_max_drawdown(equity, state.peak_equity):
            if state.in_position:
                self.broker.sell(m.symbol, state.position_qty, price, reason="max_drawdown")
            state.halted = True
            action = f"افت سرمایه از حد مجاز ({self.cfg.risk.max_drawdown_stop:.0%}) رد شد. ربات متوقف شد."
            log.error(action)
            self.stop_event.set()
        # ── مدیریت پوزیشن باز
        elif state.in_position:
            reason = None
            if price <= state.stop_price:
                reason = "stop_loss"
            elif price >= state.target_price:
                reason = "take_profit"
            elif exit_signal:
                reason = "signal"
            if reason:
                order = self.broker.sell(m.symbol, state.position_qty, price, reason=reason)
                pnl = state.trades[-1]["pnl"]
                action = f"فروش به‌خاطر {REASON_TEXT[reason]} در {order.price:,.2f} — سود/زیان {pnl:+,.2f}"
                (log.warning if pnl < 0 else log.info)(action)
            else:
                action = "در پوزیشن — منتظر حد سود، حد ضرر یا سیگنال خروج"
        # ── ورود
        elif entry_signal:
            plan = self.risk.plan(
                equity=state.cash,
                entry_price=price * (1 + self.cfg.costs.slippage_rate),
                stop_distance=float(signals["stop_distance"].iloc[-1]),
                target_distance=float(signals["target_distance"].iloc[-1]),
            )
            # جا برای کارمزد خرید
            quantity = min(plan.quantity, state.cash / (plan.entry_price * (1 + self.cfg.costs.fee_rate)))
            if plan.is_valid and quantity > 0:
                order = self.broker.buy(m.symbol, quantity, price, reason="signal")
                state.stop_price = plan.stop_price
                state.target_price = plan.target_price
                action = (
                    f"خرید {order.quantity:.6f} در {order.price:,.2f} | "
                    f"حد ضرر {plan.stop_price:,.2f} | حد سود {plan.target_price:,.2f}"
                )
                log.info(action)
            else:
                action = "سیگنال خرید آمد ولی حجم محاسبه‌شده معتبر نبود؛ رد شد."
                log.info(action)
        else:
            action = "بیرون از بازار — منتظر سیگنال خرید"

        if new_bar:
            state.equity_history.append([bar_time, round(self.broker.equity(price), 4)])
            del state.equity_history[:-MAX_EQUITY_POINTS]
        state.last_signal_bar = bar_time
        self.broker.save()

        self.status = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "price": price,
            "bar_time": bar_time,
            "source": AutoSource.active if m.source == "auto" else m.source,
            "action": action,
            "checks": [{"text": c.text, "ok": c.ok} for c in self.strategy.explain(done)],
            "equity": self.broker.equity(price),
            "error": None,
        }
        return self.status

    # ─────────────────────────── حلقه ───────────────────────────

    def run(self, max_iterations: int | None = None) -> None:
        log.info(
            "شروع ربات (حالت کاغذی) | %s %s از %s | استراتژی %s | نقد %.2f",
            self.cfg.market.symbol, self.cfg.market.timeframe, self.cfg.market.source,
            self.strategy.name, self.broker.state.cash,
        )
        iteration = 0
        while not self.stop_event.is_set():
            try:
                self.step()
            except Exception as exc:  # یک خطای موقت شبکه نباید ربات را بکشد
                log.error("خطا در این دور (ادامه می‌دهیم): %s", str(exc).splitlines()[0])
                self.status = {**self.status, "error": str(exc)}

            iteration += 1
            if max_iterations is not None and iteration >= max_iterations:
                break
            self.stop_event.wait(self.cfg.live.poll_seconds)
        log.info("ربات متوقف شد.")

    def close_position(self, price: float, reason: str = "manual") -> None:
        """بستن دستی پوزیشن (دکمه پنل)."""
        with self.lock:
            state = self.broker.state
            if not state.in_position:
                raise ValueError("پوزیشن بازی وجود ندارد.")
            self.broker.sell(self.cfg.market.symbol, state.position_qty, price, reason=reason)
            log.info("پوزیشن به‌صورت دستی بسته شد در قیمت %.2f", price)

    def summary(self, price: float) -> str:
        s = self.broker.state
        return (
            f"وضعیت حساب کاغذی @ {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n"
            f"  نقد          : {s.cash:,.2f}\n"
            f"  حجم پوزیشن   : {s.position_qty:.8f}\n"
            f"  سود/زیان محقق: {s.realized_pnl:,.2f}\n"
            f"  کارمزد کل    : {s.total_fees:,.2f}\n"
            f"  ارزش کل حساب : {self.broker.equity(price):,.2f}\n"
            f"  تعداد معامله : {len(s.trades)}"
            + ("\n  ⛔ کلید قطع اضطراری زده شده — با paper --reset حساب را ریست کن." if s.halted else "")
        )
