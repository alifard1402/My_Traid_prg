"""معیارهای ارزیابی نتیجه بک‌تست.

«چقدر سود کرد» تنها عدد مهم نیست. یک استراتژی با ۵۰٪ سود که در میانه راه
۶۰٪ افت سرمایه داشته، عملاً غیرقابل استفاده است — هیچ انسانی تحملش نمی‌کند.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd

#: تعداد تقریبی کندل در سال، برای سالانه‌سازی معیارها
BARS_PER_YEAR = {
    "1m": 525_600, "5m": 105_120, "15m": 35_040, "30m": 17_520,
    "1h": 8_760, "4h": 2_190, "1d": 365,
}


@dataclass
class Metrics:
    initial_capital: float = 0.0
    final_equity: float = 0.0
    total_return_pct: float = 0.0
    buy_hold_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe: float = 0.0
    num_trades: int = 0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    total_fees: float = 0.0
    exposure_pct: float = 0.0
    extras: dict = field(default_factory=dict)

    def as_text(self) -> str:
        pf = "∞" if math.isinf(self.profit_factor) else f"{self.profit_factor:.2f}"
        lines = [
            "─" * 52,
            "  نتیجه بک‌تست",
            "─" * 52,
            f"  سرمایه اولیه          : {self.initial_capital:>14,.2f}",
            f"  سرمایه نهایی          : {self.final_equity:>14,.2f}",
            f"  بازده کل              : {self.total_return_pct:>13.2f}%",
            f"  بازده «بخر و نگه دار» : {self.buy_hold_return_pct:>13.2f}%",
            "",
            f"  بیشترین افت سرمایه    : {self.max_drawdown_pct:>13.2f}%   ← هرچه کمتر بهتر",
            f"  نسبت شارپ             : {self.sharpe:>14.2f}   ← بالای ۱ خوب است",
            "",
            f"  تعداد معاملات         : {self.num_trades:>14d}",
            f"  درصد معاملات برنده    : {self.win_rate_pct:>13.2f}%",
            f"  ضریب سوددهی           : {pf:>14}   ← بالای ۱.۵ خوب است",
            f"  میانگین سود هر برد    : {self.avg_win:>14,.2f}",
            f"  میانگین ضرر هر باخت   : {self.avg_loss:>14,.2f}",
            "",
            f"  مجموع کارمزد پرداختی  : {self.total_fees:>14,.2f}",
            f"  درصد زمان در بازار    : {self.exposure_pct:>13.2f}%",
            "─" * 52,
        ]
        return "\n".join(lines)


def max_drawdown(equity: pd.Series) -> float:
    """بیشترین افت از سقف قبلی، به درصد."""
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    return float(((equity - peak) / peak).min() * 100)


def sharpe_ratio(equity: pd.Series, timeframe: str, risk_free: float = 0.0) -> float:
    """بازده تعدیل‌شده با ریسک، سالانه‌شده."""
    returns = equity.pct_change().dropna()
    if len(returns) < 2:
        return 0.0
    std = float(returns.std())
    if std == 0:
        return 0.0
    periods = BARS_PER_YEAR.get(timeframe, 365)
    excess = float(returns.mean()) - risk_free / periods
    return float(excess / std * np.sqrt(periods))


def compute(
    equity_curve: pd.Series,
    trades: Sequence,
    price: pd.Series,
    initial_capital: float,
    timeframe: str,
) -> Metrics:
    """همه معیارها را از منحنی سرمایه و لیست معاملات حساب می‌کند."""
    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    final_equity = float(equity_curve.iloc[-1]) if len(equity_curve) else initial_capital
    buy_hold = (
        float(price.iloc[-1] / price.iloc[0] - 1) * 100 if len(price) > 1 else 0.0
    )

    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = math.inf if gross_profit > 0 else 0.0

    bars_in_market = sum(t.bars_held for t in trades)
    exposure = bars_in_market / len(equity_curve) * 100 if len(equity_curve) else 0.0

    return Metrics(
        initial_capital=initial_capital,
        final_equity=final_equity,
        total_return_pct=(final_equity / initial_capital - 1) * 100,
        buy_hold_return_pct=buy_hold,
        max_drawdown_pct=max_drawdown(equity_curve),
        sharpe=sharpe_ratio(equity_curve, timeframe),
        num_trades=len(trades),
        win_rate_pct=len(wins) / len(pnls) * 100 if pnls else 0.0,
        profit_factor=profit_factor,
        avg_win=gross_profit / len(wins) if wins else 0.0,
        avg_loss=-gross_loss / len(losses) if losses else 0.0,
        total_fees=sum(t.fees for t in trades),
        exposure_pct=min(exposure, 100.0),
    )
