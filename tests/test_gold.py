"""تست‌های بخش طلا: نمادها، منابع داده، استراتژی‌ها، تنظیمات پنل و قضاوت بک‌تست."""

from __future__ import annotations

import json

import pytest

from trading_bot.backtest import Backtester
from trading_bot.backtest.verdict import judge
from trading_bot.config import Config, clear_overrides, save_overrides
from trading_bot.data import AutoSource, BinanceSource, NobitexSource, SampleSource, YahooSource, is_gold
from trading_bot.data import auto as auto_mod
from trading_bot.data.yahoo import resample
from trading_bot.risk import RiskManager
from trading_bot.strategy import STRATEGIES, get_strategy


def test_gold_aliases_resolve_per_source():
    assert NobitexSource().resolve_symbol("XAUUSD") == "PAXGUSDT"
    assert BinanceSource().resolve_symbol("gold") == "PAXGUSDT"
    assert YahooSource().resolve_symbol("XAUUSD") == "GC=F"
    assert NobitexSource().resolve_symbol("PAXGIRT") == "PAXGIRT"
    assert is_gold("XAUUSD") and is_gold("PAXGUSDT") and not is_gold("BTCUSDT")


def test_sample_gold_prices_look_like_gold():
    df = SampleSource().fetch_ohlcv("XAUUSD", "4h", 50)
    assert 1500 < df["close"].iloc[0] < 4000


def test_yahoo_parser_drops_null_rows():
    payload = {"chart": {"error": None, "result": [{
        "timestamp": [1700000000, 1700003600, 1700007200],
        "indicators": {"quote": [{
            "open": [1.0, None, 3.0], "high": [2.0, None, 4.0],
            "low": [0.5, None, 2.5], "close": [1.5, None, 3.5], "volume": [10, None, 30],
        }]},
    }]}}
    df = YahooSource.parse(payload, "GC=F")
    assert len(df) == 2
    assert df["close"].tolist() == [1.5, 3.5]


def test_yahoo_parser_reports_errors():
    with pytest.raises(ValueError):
        YahooSource.parse({"chart": {"result": None, "error": {"code": "Not Found"}}}, "XXX")


def test_resample_hourly_to_4h():
    df = SampleSource().fetch_ohlcv("XAUUSD", "1h", 48)
    out = resample(df, "240min")
    first = df.loc[out.index[1]: out.index[1] + __import__("pandas").Timedelta(hours=3)]
    assert out["high"].iloc[1] == first["high"].max()
    assert out["open"].iloc[1] == first["open"].iloc[0]
    assert out["close"].iloc[1] == first["close"].iloc[-1]


def test_auto_source_falls_back_and_remembers(monkeypatch):
    calls = []

    class Down:
        def fetch_ohlcv(self, *a):
            calls.append("down")
            raise ConnectionError("blocked")

    import trading_bot.data as data

    monkeypatch.setattr(AutoSource, "active", None)
    monkeypatch.setattr(data, "get_source", lambda n: Down() if n == "nobitex" else SampleSource())
    df = AutoSource(order=("nobitex", "sample")).fetch_ohlcv("XAUUSD", "4h", 10)
    assert len(df) == 10 and AutoSource.active == "sample"

    AutoSource(order=("nobitex", "sample")).fetch_ohlcv("XAUUSD", "4h", 10)
    assert calls == ["down"]  # دفعه دوم مستقیم سراغ منبع سالم رفت


def test_auto_source_error_lists_every_source(monkeypatch):
    import trading_bot.data as data

    class Down:
        def fetch_ohlcv(self, *a):
            raise ConnectionError("blocked")

    monkeypatch.setattr(AutoSource, "active", None)
    monkeypatch.setattr(data, "get_source", lambda n: Down())
    with pytest.raises(ConnectionError, match="nobitex.*\n.*yahoo"):
        AutoSource(order=("nobitex", "yahoo")).fetch_ohlcv("XAUUSD", "4h", 10)
    assert auto_mod.DEFAULT_ORDER[0] == "nobitex"


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_every_strategy_runs_and_describes_itself(name):
    df = SampleSource(seed=3).fetch_ohlcv("XAUUSD", "4h", 1500)
    strategy = get_strategy(name)
    result = Backtester(strategy, RiskManager()).run(df)
    assert result.metrics.num_trades >= 1

    info = strategy.describe()
    assert info["title"] and info["description"]
    assert set(info["params"]) == set(info["defaults"])
    for key, value in info["defaults"].items():
        spec = info["params"][key]
        assert spec["min"] <= value <= spec["max"], key
    assert strategy.explain(df)


@pytest.mark.parametrize("name", list(STRATEGIES))
def test_strategies_do_not_look_ahead(name):
    """سیگنال کندل‌های گذشته نباید با اضافه شدن کندل‌های آینده عوض شود."""
    df = SampleSource(seed=9).fetch_ohlcv("XAUUSD", "4h", 800)
    strategy = get_strategy(name)
    full = strategy.generate(df)
    partial = strategy.generate(df.iloc[:600])
    for col in ("entry", "exit"):
        assert full[col].iloc[:600].equals(partial[col])


def test_strategy_keeps_int_params_int_and_drops_unknown():
    s = get_strategy("ema_trend", ema_fast=10.0, bogus=1)
    assert s.params["ema_fast"] == 10 and isinstance(s.params["ema_fast"], int)
    assert "bogus" not in s.params


def test_panel_overrides_layer_on_top_of_yaml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "strategy:\n  name: ema_trend\n  params: {ema_fast: 12}\n", encoding="utf-8")
    cfg = Config.load("config.yaml")

    save_overrides(cfg, {"strategy": {"name": "rsi_pullback", "params": {"rsi_period": 7}},
                         "risk": {"risk_per_trade": 0.02}})
    loaded = Config.load("config.yaml")
    assert loaded.strategy.name == "rsi_pullback"
    assert loaded.strategy.params == {"rsi_period": 7}  # پارامترهای قبلی نشت نکرد
    assert loaded.risk.risk_per_trade == 0.02
    assert "ema_fast" in (tmp_path / "config.yaml").read_text(encoding="utf-8")  # yaml دست نخورد

    clear_overrides(loaded)
    assert Config.load("config.yaml").strategy.name == "ema_trend"


def test_invalid_panel_settings_are_never_saved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("{}", encoding="utf-8")
    cfg = Config.load("config.yaml")
    with pytest.raises(ValueError):
        save_overrides(cfg, {"risk": {"risk_per_trade": 0.9}})
    assert not (tmp_path / "data" / "panel_settings.json").exists()


def test_verdict_flags_too_few_trades_and_losses():
    df = SampleSource(seed=1).fetch_ohlcv("XAUUSD", "4h", 600)
    m = Backtester(get_strategy("ema_trend"), RiskManager()).run(df).metrics
    m.num_trades, m.total_return_pct = 3, -5.0
    v = judge(m)
    titles = [f["title"] for f in v["findings"]]
    assert "معامله خیلی کم" in titles and "زیان‌ده" in titles
    assert v["level"] in ("bad", "ok")
    json.dumps(v)  # قابل ارسال به پنل
