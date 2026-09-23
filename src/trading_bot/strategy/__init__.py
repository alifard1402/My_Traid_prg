"""لایه استراتژی — منطق «کِی بخر، کِی بفروش»."""

from __future__ import annotations

from typing import Any

from .base import Check, Param, Strategy
from .donchian import DonchianBreakoutStrategy
from .ema_trend import EmaTrendStrategy
from .rsi_pullback import RsiPullbackStrategy

STRATEGIES: dict[str, type[Strategy]] = {
    "ema_trend": EmaTrendStrategy,
    "donchian_breakout": DonchianBreakoutStrategy,
    "rsi_pullback": RsiPullbackStrategy,
}


def get_strategy(name: str, **params: Any) -> Strategy:
    if name not in STRATEGIES:
        raise ValueError(
            f"استراتژی ناشناخته: {name}. مقادیر مجاز: {', '.join(STRATEGIES)}"
        )
    return STRATEGIES[name](**params)


__all__ = [
    "Strategy", "Param", "Check", "EmaTrendStrategy", "DonchianBreakoutStrategy",
    "RsiPullbackStrategy", "STRATEGIES", "get_strategy",
]
