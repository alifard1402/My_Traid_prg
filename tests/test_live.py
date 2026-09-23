"""تست‌های حلقه زنده — مهم‌ترینش: هر سیگنال فقط یک بار اجرا شود."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trading_bot.config import Config
from trading_bot.live import LiveTrader, closed_bars
from trading_bot.strategy import STRATEGIES
from trading_bot.strategy.base import Strategy


class OneShot(Strategy):
    """روی کندل مشخصی سیگنال خرید می‌دهد."""

    name = "one_shot"
    entry_at: pd.Timestamp | None = None

    @property
    def warmup(self) -> int:
        return 0

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        out["entry"] = df.index == self.entry_at
        out["exit"] = False
        out["stop_distance"] = 5.0
        out["target_distance"] = 50.0
        return out


def bars(closes, start="2024-01-01"):
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {"open": closes, "high": closes + 1, "low": closes - 1, "close": closes, "volume": 1.0},
        index=pd.date_range(start, periods=len(closes), freq="4h", tz="UTC"),
    )


@pytest.fixture
def trader(tmp_path):
    cfg = Config()
    cfg.live.state_file = str(tmp_path / "state.json")
    cfg.costs.fee_rate = 0.0
    cfg.costs.slippage_rate = 0.0
    t = LiveTrader(cfg)
    t.strategy = OneShot()
    return t


def test_closed_bars_excludes_forming_candle():
    df = bars([1, 2, 3])
    now = df.index[-1] + pd.Timedelta(hours=1)  # کندل آخر هنوز در حال شکل‌گیری است
    assert len(closed_bars(df, "4h", now)) == 2


def test_signal_is_acted_on_only_once(trader):
    """باگ کلاسیک: بعد از خوردن حد ضرر، نباید با همان سیگنال قدیمی دوباره بخرد."""
    df = bars([100] * 10)
    trader.strategy.entry_at = df.index[-2]
    now = df.index[-1] + pd.Timedelta(hours=1)

    trader.step(df, now)
    assert trader.broker.state.in_position

    crash = df.copy()
    crash.iloc[-1, crash.columns.get_loc("close")] = 90.0  # زیر حد ضرر (۹۵)
    trader.step(crash, now)
    assert not trader.broker.state.in_position
    assert trader.broker.state.trades[-1]["exit_reason"] == "stop_loss"

    trader.step(df, now + pd.Timedelta(minutes=1))  # همان کندل بسته‌شده، دور بعد
    assert not trader.broker.state.in_position
    assert len(trader.broker.state.orders) == 2


def test_new_closed_bar_is_recorded_in_equity_history(trader):
    df = bars([100] * 10)
    trader.step(df, df.index[-1] + pd.Timedelta(hours=1))
    trader.step(df, df.index[-1] + pd.Timedelta(hours=2))  # همان کندل → نقطه جدید نه
    assert len(trader.broker.state.equity_history) == 1


def test_drawdown_switch_halts_and_stops_loop(trader):
    df = bars([100] * 10)
    trader.strategy.entry_at = df.index[-2]
    now = df.index[-1] + pd.Timedelta(hours=1)
    trader.step(df, now)
    trader.broker.state.stop_price = 0.0  # حد ضرری که نمی‌خورد
    trader.broker.state.peak_equity = 10_000.0

    trader.step(bars([100] * 9 + [10]), now)

    assert trader.broker.state.halted
    assert trader.stop_event.is_set()
    assert not trader.broker.state.in_position


def test_status_contains_plain_language_checks(tmp_path):
    from trading_bot.data import SampleSource

    cfg = Config()
    cfg.live.state_file = str(tmp_path / "s.json")
    cfg.market.source = "sample"
    df = SampleSource().fetch_ohlcv("XAUUSD", "4h", 400)
    for name in STRATEGIES:
        cfg.strategy.name = name
        cfg.strategy.params = {}
        status = LiveTrader(cfg).step(df)
        assert status["checks"], name
        assert all(isinstance(c["text"], str) and c["text"] for c in status["checks"])
