"""لایه استراتژی — منطق «کِی بخر، کِی بفروش»."""

from __future__ import annotations

from typing import Any

from .base import Strategy
from .ema_trend import EmaTrendStrategy

STRATEGIES: dict[str, type[Strategy]] = {
    "ema_trend": EmaTrendStrategy,
}


def get_strategy(name: str, **params: Any) -> Strategy:
    if name not in STRATEGIES:
        raise ValueError(
            f"استراتژی ناشناخته: {name}. مقادیر مجاز: {', '.join(STRATEGIES)}"
        )
    return STRATEGIES[name](**params)


__all__ = ["Strategy", "EmaTrendStrategy", "STRATEGIES", "get_strategy"]
