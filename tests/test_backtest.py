"""تست‌های موتور بک‌تست — اینجا مهم‌ترین تست‌های پروژه‌اند.

اگر موتور بک‌تست اشتباه حساب کند، همه نتیجه‌ها دروغ‌اند و تو با اعتماد
به یک عدد غلط پول واقعی وارد می‌کنی.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trading_bot.backtest import Backtester
from trading_bot.data import SampleSource
from trading_bot.risk import RiskManager
from trading_bot.strategy import EmaTrendStrategy
from trading_bot.strategy.base import Strategy


def make_bars(closes: list[float], spread: float = 0.5) -> pd.DataFrame:
    """کندل‌های ساده و قابل پیش‌بینی از روی لیست قیمت بسته شدن."""
    closes_arr = np.array(closes, dtype=float)
    opens = np.concatenate([[closes_arr[0]], closes_arr[:-1]])
    return pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, closes_arr) + spread,
            "low": np.minimum(opens, closes_arr) - spread,
            "close": closes_arr,
            "volume": np.full(len(closes), 100.0),
        },
        index=pd.date_range("2024-01-01", periods=len(closes), freq="4h", tz="UTC"),
    )


class ScriptedStrategy(Strategy):
    """استراتژی ساختگی: دقیقاً روی کندل‌های مشخصی سیگنال می‌دهد."""

    name = "scripted"

    def __init__(self, entry_bars, exit_bars=(), stop_distance=10.0, target_distance=1e9):
        super().__init__()
        self.entry_bars = set(entry_bars)
        self.exit_bars = set(exit_bars)
        self.stop_distance = stop_distance
        self.target_distance = target_distance

    @property
    def warmup(self) -> int:
        return 0

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        positions = range(len(df))
        out["entry"] = [i in self.entry_bars for i in positions]
        out["exit"] = [i in self.exit_bars for i in positions]
        out["stop_distance"] = self.stop_distance
        out["target_distance"] = self.target_distance
        return out


def make_backtester(strategy, **kwargs) -> Backtester:
    defaults = dict(
        risk=RiskManager(risk_per_trade=0.01, max_position_pct=0.95),
        initial_capital=10_000.0,
        fee_rate=0.0,
        slippage_rate=0.0,
        timeframe="4h",
    )
    return Backtester(strategy=strategy, **{**defaults, **kwargs})


# ───────────────────────── درستی اجرا ─────────────────────────


def test_entry_fills_on_next_bar_open_not_signal_bar():
    """مهم‌ترین تست: هیچ نگاهی به آینده نباید وجود داشته باشد.

    سیگنال روی کندل ۲ داده می‌شود؛ ورود باید با قیمتِ *باز شدنِ* کندل ۳
    انجام شود، نه با قیمت بسته شدن کندل ۲ که در آن لحظه هنوز نمی‌دانستیم.
    """
    df = make_bars([100, 101, 102, 103, 104, 105, 106])
    bt = make_backtester(ScriptedStrategy(entry_bars=[2], exit_bars=[5]))

    result = bt.run(df)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_time == df.index[3]
    assert trade.entry_price == pytest.approx(df["open"].iloc[3])
    assert trade.entry_price != pytest.approx(df["close"].iloc[2] + 1)


def test_exit_signal_fills_on_next_bar_open():
    df = make_bars([100, 101, 102, 103, 104, 105, 106])
    bt = make_backtester(ScriptedStrategy(entry_bars=[0], exit_bars=[3]))

    trade = bt.run(df).trades[0]

    assert trade.exit_reason == "signal"
    assert trade.exit_time == df.index[4]
    assert trade.exit_price == pytest.approx(df["open"].iloc[4])


def test_stop_loss_triggers_and_caps_the_loss():
    """وقتی قیمت سقوط می‌کند، ضرر باید نزدیک ریسکِ تعیین‌شده بماند."""
    df = make_bars([100, 100, 100, 100, 70, 60, 50])
    bt = make_backtester(
        ScriptedStrategy(entry_bars=[0], stop_distance=10.0), initial_capital=10_000.0
    )

    result = bt.run(df)
    trade = result.trades[0]

    assert trade.exit_reason == "stop_loss"
    # ریسک تعیین‌شده ۱٪ از ۱۰٬۰۰۰ = ۱۰۰ بود. با گپِ قیمت ممکن است بیشتر
    # شود (لغزش واقعی بازار)، ولی نباید فاجعه‌بار شود.
    assert trade.pnl < 0
    assert abs(trade.pnl) < 500


def test_take_profit_triggers():
    df = make_bars([100, 100, 100, 130, 140, 150])
    bt = make_backtester(
        ScriptedStrategy(entry_bars=[0], stop_distance=10.0, target_distance=25.0)
    )

    trade = bt.run(df).trades[0]

    assert trade.exit_reason == "take_profit"
    assert trade.pnl > 0


def test_stop_is_checked_before_target_in_the_same_bar():
    """اگر در یک کندل هر دو در دسترس باشند، محافظه‌کارانه حد ضرر را می‌گیریم."""
    df = make_bars([100, 100, 100])
    df.loc[df.index[2], ["low", "high"]] = [50.0, 200.0]  # کندلِ پرنوسان
    bt = make_backtester(
        ScriptedStrategy(entry_bars=[0], stop_distance=10.0, target_distance=20.0)
    )

    trade = bt.run(df).trades[0]

    assert trade.exit_reason == "stop_loss"


def test_no_second_position_while_one_is_open():
    df = make_bars([100, 101, 102, 103, 104, 105])
    bt = make_backtester(ScriptedStrategy(entry_bars=[0, 1, 2, 3]))

    result = bt.run(df)

    assert len(result.trades) == 1  # سیگنال‌های تکراری نادیده گرفته می‌شوند


# ───────────────────────── هزینه‌ها ─────────────────────────


def test_fees_reduce_pnl():
    df = make_bars([100, 101, 102, 103, 104, 105])
    free = make_backtester(ScriptedStrategy(entry_bars=[0], exit_bars=[3]), fee_rate=0.0)
    costly = make_backtester(ScriptedStrategy(entry_bars=[0], exit_bars=[3]), fee_rate=0.01)

    free_pnl = free.run(df).trades[0].pnl
    costly_result = costly.run(df)

    assert costly_result.trades[0].pnl < free_pnl
    assert costly_result.metrics.total_fees > 0


def test_slippage_worsens_both_sides():
    df = make_bars([100, 101, 102, 103, 104, 105])
    clean = make_backtester(ScriptedStrategy(entry_bars=[0], exit_bars=[3]), slippage_rate=0.0)
    slipped = make_backtester(ScriptedStrategy(entry_bars=[0], exit_bars=[3]), slippage_rate=0.01)

    clean_trade = clean.run(df).trades[0]
    slipped_trade = slipped.run(df).trades[0]

    assert slipped_trade.entry_price > clean_trade.entry_price  # گران‌تر می‌خریم
    assert slipped_trade.exit_price < clean_trade.exit_price    # ارزان‌تر می‌فروشیم


# ───────────────────────── محافظ‌ها ─────────────────────────


def test_max_drawdown_switch_halts_trading():
    """کلید قطع اضطراری: پارامترها عمداً بی‌احتیاط‌اند تا محافظ فعال شود."""
    df = make_bars([100] * 5 + [50, 40, 30, 20, 10] + [100] * 10)
    bt = make_backtester(
        ScriptedStrategy(entry_bars=[0], stop_distance=200.0),  # حد ضرری که هرگز نمی‌خورد
        risk=RiskManager(risk_per_trade=1.0, max_position_pct=0.95, max_drawdown_stop=0.10),
    )

    result = bt.run(df)

    assert result.stopped_early


def test_equity_curve_aligns_with_bars_and_stays_finite():
    df = make_bars(list(np.linspace(100, 120, 40)))
    result = make_backtester(ScriptedStrategy(entry_bars=[5], exit_bars=[20])).run(df)

    assert len(result.equity_curve) == len(df) - 1
    assert np.isfinite(result.equity_curve).all()
    assert (result.equity_curve > 0).all()


def test_flat_strategy_preserves_capital_exactly():
    df = make_bars(list(np.linspace(100, 200, 50)))
    result = make_backtester(ScriptedStrategy(entry_bars=[])).run(df)

    assert result.trades == []
    assert result.metrics.final_equity == pytest.approx(10_000.0)
    assert result.metrics.total_return_pct == pytest.approx(0.0)


def test_rejects_data_shorter_than_warmup():
    df = make_bars([100, 101, 102])
    bt = make_backtester(EmaTrendStrategy())

    with pytest.raises(ValueError, match="داده کافی نیست"):
        bt.run(df)


# ───────────────────────── مسیر کامل ─────────────────────────


def test_end_to_end_on_sample_data_is_reproducible():
    df = SampleSource(seed=7).fetch_ohlcv("BTCUSDT", "4h", 800)
    bt = make_backtester(EmaTrendStrategy(), fee_rate=0.001, slippage_rate=0.0005)

    first = bt.run(df)
    second = bt.run(df)

    assert first.metrics.final_equity == pytest.approx(second.metrics.final_equity)
    assert len(first.trades) == len(second.trades)
    assert first.metrics.num_trades >= 0
    assert -100 < first.metrics.max_drawdown_pct <= 0
