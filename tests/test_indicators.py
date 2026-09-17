import numpy as np
import pandas as pd
import pytest

from trading_bot.indicators import atr, crossover, crossunder, ema, rsi, sma


@pytest.fixture
def prices():
    return pd.Series([10, 11, 12, 13, 14, 13, 12, 11, 10, 11, 12, 13], dtype=float)


def test_ema_follows_trend(prices):
    result = ema(prices, 3)
    assert len(result) == len(prices)
    assert result.notna().all()
    # روی یک سری صعودی، EMA باید از قیمت عقب‌تر ولی رو به بالا باشد
    assert result.iloc[4] < prices.iloc[4]
    assert result.iloc[4] > result.iloc[0]


def test_sma_is_plain_average(prices):
    result = sma(prices, 3)
    assert result.iloc[:2].isna().all()  # قبل از پر شدن پنجره مقداری ندارد
    assert result.iloc[2] == pytest.approx((10 + 11 + 12) / 3)


def test_atr_is_positive_and_reacts_to_volatility():
    calm = pd.DataFrame({
        "high": np.full(50, 101.0), "low": np.full(50, 99.0),
        "close": np.full(50, 100.0), "open": np.full(50, 100.0),
    })
    wild = pd.DataFrame({
        "high": np.full(50, 120.0), "low": np.full(50, 80.0),
        "close": np.full(50, 100.0), "open": np.full(50, 100.0),
    })
    assert atr(calm).iloc[-1] > 0
    assert atr(wild).iloc[-1] > atr(calm).iloc[-1]


def test_rsi_bounds():
    rising = pd.Series(np.arange(1, 60), dtype=float)
    falling = pd.Series(np.arange(60, 1, -1), dtype=float)
    assert rsi(rising).iloc[-1] > 90
    assert rsi(falling).iloc[-1] < 10
    assert rsi(rising).between(0, 100).all()


def test_crossover_fires_once():
    fast = pd.Series([1.0, 1.0, 3.0, 4.0, 4.0])
    slow = pd.Series([2.0, 2.0, 2.0, 2.0, 2.0])
    up = crossover(fast, slow)
    assert up.tolist() == [False, False, True, False, False]
    assert not crossunder(fast, slow).any()
