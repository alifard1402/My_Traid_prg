"""Tests for the GoldPilot Recovery simulator's basket rules (mt4/sim)."""

from __future__ import annotations

import sys
from pathlib import Path

from dataclasses import replace

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mt4" / "sim"))
from goldpilot_sim import Basket, Params, SignalRow, simulate  # noqa: E402


def bars(prices: list[float], start: str = "2026-01-05 10:00") -> pd.DataFrame:
    """One M1 bar per price; open = previous close, no wicks."""
    idx = pd.date_range(start, periods=len(prices), freq="1min")
    opens = [prices[0]] + prices[:-1]
    return pd.DataFrame({"open": opens, "high": [max(a, b) for a, b in zip(opens, prices)],
                         "low": [min(a, b) for a, b in zip(opens, prices)], "close": prices}, index=idx)


def buy_signal_at(t: str) -> SignalRow:
    return SignalRow(pd.Timestamp(t), 1, True, True, False, False, False, 1.0)


P = Params(spread=0.0, use_session=False, use_friday_cutoff=False, close_before_weekend=False,
           min_atr_ratio=0.0, trail_usd=0.0, deep_trades=0)


def test_price_levels_match_money():
    b = Basket(1, pd.Timestamp("2026-01-05"), [(100.0, 0.01), (90.0, 0.01)])
    assert b.pnl(95.0, 0) == pytest.approx(0.0)
    assert b.bid_for_money(10.0, 0) == pytest.approx(100.0)       # +10 on 0.02 lot = 5 price
    s = Basket(-1, pd.Timestamp("2026-01-05"), [(100.0, 0.01)])
    assert s.bid_for_money(10.0, 0.3) == pytest.approx(89.7)       # sell closes at ask = bid + spread
    assert s.bid_for_last(-10.0, 0.3) == pytest.approx(109.7)


def test_single_trade_takes_ten_dollars():
    m1 = bars([2000.0, 2004.0, 2008.0, 2012.0])
    res = simulate(m1, [buy_signal_at("2026-01-05 10:00")], P)
    row = res.baskets.iloc[0]
    assert row.trades == 1 and row.reason == "target"
    assert row.result == pytest.approx(10.0)


def test_recovery_adds_and_one_third_target():
    # 2000 -> 1970: adds at 1990, 1980 and 1970 (4 trades, avg 1985);
    # worst at 1970 = -30-20-10-0 = -60 -> target = max(10, 60/3) = 20 -> closes at 1990
    m1 = bars([2000.0, 1990.0, 1980.0, 1970.0, 1985.0, 2000.0])
    res = simulate(m1, [buy_signal_at("2026-01-05 10:00")], P)
    row = res.baskets.iloc[0]
    assert row.trades == 4
    assert row.worst == pytest.approx(-60.0)
    assert row.result == pytest.approx(20.0)
    assert row.reason == "target"


def test_emergency_stop_caps_the_loss():
    m1 = bars([2000.0 - 5 * k for k in range(30)])
    res = simulate(m1, [buy_signal_at("2026-01-05 10:00")], P)
    row = res.baskets.iloc[0]
    assert row.reason == "stop"
    assert row.result == pytest.approx(-150.0)
    assert row.trades == 5


def test_trailing_keeps_the_profit_running():
    # +10 reached at 2010, price runs to 2030, falls back: floor = 30 - 10 = +20
    m1 = bars([2000.0, 2010.0, 2020.0, 2030.0, 2025.0, 2015.0, 2000.0])
    res = simulate(m1, [buy_signal_at("2026-01-05 10:00")], replace(P, trail_usd=10.0))
    row = res.baskets.iloc[0]
    assert row.reason == "target"
    assert row.result == pytest.approx(20.0)


def test_trailing_never_closes_below_the_target():
    m1 = bars([2000.0, 2010.0, 2012.0, 2000.0])
    res = simulate(m1, [buy_signal_at("2026-01-05 10:00")], replace(P, trail_usd=10.0))
    assert res.baskets.iloc[0].result == pytest.approx(10.0)


def test_deep_basket_uses_deep_target():
    # 5 trades (2000..1960), worst -100 at 1960: 1/3 rule would need +33; deep target is +10
    m1 = bars([2000.0, 1990.0, 1980.0, 1970.0, 1960.0, 1985.0])
    res = simulate(m1, [buy_signal_at("2026-01-05 10:00")], replace(P, deep_trades=5, deep_target_usd=10.0))
    row = res.baskets.iloc[0]
    assert row.trades == 5
    assert row.result == pytest.approx(10.0)
