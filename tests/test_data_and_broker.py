import json

import pandas as pd
import pytest

from trading_bot.broker import PaperBroker
from trading_bot.config import Config
from trading_bot.data import SampleSource, cache_path, load_cache, save_cache
from trading_bot.data.base import OHLCV_COLUMNS
from trading_bot.strategy import STRATEGIES


# ───────────────────────── داده ─────────────────────────


def test_sample_source_shape_and_sanity():
    df = SampleSource(seed=1).fetch_ohlcv("BTCUSDT", "4h", 300)

    assert len(df) == 300
    assert list(df.columns) == OHLCV_COLUMNS
    assert df.index.is_monotonic_increasing
    assert df.index.tz is not None
    assert (df["high"] >= df["low"]).all()
    assert (df["high"] >= df[["open", "close"]].max(axis=1)).all()
    assert (df["low"] <= df[["open", "close"]].min(axis=1)).all()
    assert (df["close"] > 0).all()


def test_sample_source_is_deterministic_per_seed():
    a = SampleSource(seed=5).fetch_ohlcv("BTCUSDT", "1h", 100)
    b = SampleSource(seed=5).fetch_ohlcv("BTCUSDT", "1h", 100)
    c = SampleSource(seed=6).fetch_ohlcv("BTCUSDT", "1h", 100)

    pd.testing.assert_series_equal(a["close"], b["close"])
    assert not a["close"].equals(c["close"])


def test_validate_drops_corrupt_candles():
    src = SampleSource()
    bad = pd.DataFrame(
        {
            "open": [10.0, 10.0],
            "high": [11.0, 5.0],   # کندل دوم خراب است: high < low
            "low": [9.0, 12.0],
            "close": [10.5, 10.0],
            "volume": [1.0, 1.0],
        },
        index=pd.to_datetime(["2024-01-01", "2024-01-02"], utc=True),
    )
    assert len(src.validate(bad)) == 1


def test_unknown_timeframe_is_rejected():
    with pytest.raises(ValueError, match="تایم‌فریم ناشناخته"):
        SampleSource().fetch_ohlcv("BTCUSDT", "7s", 10)


def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    df = SampleSource(seed=3).fetch_ohlcv("BTCUSDT", "4h", 50)

    path = save_cache(df, "sample", "BTCUSDT", "4h")
    restored = load_cache("sample", "BTCUSDT", "4h")

    assert path == cache_path("sample", "BTCUSDT", "4h")
    pd.testing.assert_frame_equal(df, restored, check_freq=False)


# ───────────────────────── بروکر کاغذی ─────────────────────────


def test_buy_then_sell_updates_cash_and_pnl(tmp_path):
    broker = PaperBroker(
        initial_capital=1000.0, fee_rate=0.0, slippage_rate=0.0,
        state_file=tmp_path / "state.json",
    )

    broker.buy("BTCUSDT", quantity=2.0, price=100.0)
    assert broker.state.cash == pytest.approx(800.0)
    assert broker.state.in_position

    broker.sell("BTCUSDT", quantity=2.0, price=120.0)
    assert broker.state.cash == pytest.approx(1040.0)
    assert broker.state.realized_pnl == pytest.approx(40.0)
    assert not broker.state.in_position


def test_fees_and_slippage_are_charged(tmp_path):
    broker = PaperBroker(
        initial_capital=1000.0, fee_rate=0.001, slippage_rate=0.001,
        state_file=tmp_path / "state.json",
    )

    order = broker.buy("BTCUSDT", quantity=1.0, price=100.0)

    assert order.price == pytest.approx(100.1)  # لغزش: گران‌تر خریدیم
    assert order.fee == pytest.approx(0.1001)
    assert broker.state.total_fees > 0


def test_cannot_overspend(tmp_path):
    broker = PaperBroker(initial_capital=100.0, state_file=tmp_path / "state.json")
    with pytest.raises(ValueError, match="موجودی کافی نیست"):
        broker.buy("BTCUSDT", quantity=10.0, price=100.0)


def test_cannot_sell_without_position(tmp_path):
    broker = PaperBroker(initial_capital=100.0, state_file=tmp_path / "state.json")
    with pytest.raises(ValueError, match="پوزیشنی برای فروش"):
        broker.sell("BTCUSDT", quantity=1.0, price=100.0)


def test_state_survives_restart(tmp_path):
    path = tmp_path / "state.json"
    first = PaperBroker(initial_capital=1000.0, fee_rate=0.0, slippage_rate=0.0, state_file=path)
    first.buy("BTCUSDT", quantity=1.0, price=100.0)

    second = PaperBroker(initial_capital=1000.0, state_file=path)

    assert second.state.cash == pytest.approx(900.0)
    assert second.state.position_qty == pytest.approx(1.0)
    assert json.loads(path.read_text(encoding="utf-8"))["position_qty"] == pytest.approx(1.0)


def test_equity_marks_position_to_market(tmp_path):
    broker = PaperBroker(
        initial_capital=1000.0, fee_rate=0.0, slippage_rate=0.0,
        state_file=tmp_path / "state.json",
    )
    broker.buy("BTCUSDT", quantity=2.0, price=100.0)

    assert broker.equity(mark_price=150.0) == pytest.approx(800 + 300)


# ───────────────────────── تنظیمات ─────────────────────────


def test_config_loads_shipped_file():
    cfg = Config.load("config.yaml", use_overrides=False)
    assert cfg.market.symbol == "XAUUSD"
    assert cfg.strategy.name in STRATEGIES
    assert 0 < cfg.risk.risk_per_trade <= 0.1


def test_config_rejects_reckless_risk(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("risk:\n  risk_per_trade: 0.5\n", encoding="utf-8")
    with pytest.raises(ValueError, match="risk_per_trade"):
        Config.load(path)


def test_config_rejects_leverage(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("risk:\n  max_position_pct: 3.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="max_position_pct"):
        Config.load(path)


def test_missing_config_gives_helpful_error():
    with pytest.raises(FileNotFoundError, match="فایل تنظیمات پیدا نشد"):
        Config.load("nope.yaml")
