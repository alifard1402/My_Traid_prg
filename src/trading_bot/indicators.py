"""اندیکاتورهای تکنیکال — پیاده‌سازی مستقیم روی pandas.

عمداً از کتابخانه خارجی استفاده نشده تا ببینی هر فرمول دقیقاً چه می‌کند.
"""

from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """میانگین متحرک نمایی — به کندل‌های جدیدتر وزن بیشتری می‌دهد."""
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    """میانگین متحرک ساده."""
    return series.rolling(window=period, min_periods=period).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    """دامنه واقعی هر کندل — بزرگ‌ترینِ سه فاصله زیر."""
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """میانگین دامنه واقعی — معیار نوسان بازار.

    از آن برای تعیین حد ضرر استفاده می‌کنیم: در بازار پرنوسان حد ضرر دورتر،
    در بازار آرام نزدیک‌تر. حد ضررِ درصدیِ ثابت این را نمی‌فهمد.
    """
    return true_range(df).ewm(alpha=1 / period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """شاخص قدرت نسبی — بین ۰ تا ۱۰۰. بالای ۷۰ اشباع خرید، زیر ۳۰ اشباع فروش."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return (100 - 100 / (1 + rs)).fillna(100.0)


def crossover(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """True روی کندلی که fast از پایینِ slow به بالا عبور کرده."""
    return (fast > slow) & (fast.shift(1) <= slow.shift(1))


def crossunder(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """True روی کندلی که fast از بالای slow به پایین عبور کرده."""
    return (fast < slow) & (fast.shift(1) >= slow.shift(1))
