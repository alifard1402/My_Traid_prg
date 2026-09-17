"""خواندن و اعتبارسنجی فایل تنظیمات."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")


@dataclass
class MarketConfig:
    symbol: str = "BTCUSDT"
    timeframe: str = "4h"
    source: str = "sample"


@dataclass
class StrategyConfig:
    name: str = "ema_trend"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskConfig:
    initial_capital: float = 1000.0
    risk_per_trade: float = 0.01
    max_position_pct: float = 0.95
    max_drawdown_stop: float = 0.25


@dataclass
class CostConfig:
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005


@dataclass
class LiveConfig:
    mode: str = "paper"
    poll_seconds: int = 60
    state_file: str = "data/paper_state.json"


@dataclass
class Config:
    market: MarketConfig = field(default_factory=MarketConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    costs: CostConfig = field(default_factory=CostConfig)
    live: LiveConfig = field(default_factory=LiveConfig)

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONFIG_PATH) -> "Config":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"فایل تنظیمات پیدا نشد: {path}\n"
                "از ریشه پروژه اجرا کن، یا با --config مسیرش را بده."
            )
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        cfg = cls(
            market=MarketConfig(**raw.get("market", {})),
            strategy=StrategyConfig(**raw.get("strategy", {})),
            risk=RiskConfig(**raw.get("risk", {})),
            costs=CostConfig(**raw.get("costs", {})),
            live=LiveConfig(**raw.get("live", {})),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if not 0 < self.risk.risk_per_trade <= 0.1:
            raise ValueError(
                "risk_per_trade باید بین ۰ و ۰.۱ باشد. "
                "ریسک بیش از ۱۰٪ در هر معامله یعنی نابودی حساب."
            )
        if not 0 < self.risk.max_position_pct <= 1.0:
            raise ValueError("max_position_pct باید بین ۰ و ۱ باشد (بدون اهرم).")
        if self.risk.initial_capital <= 0:
            raise ValueError("initial_capital باید مثبت باشد.")
        if self.live.mode not in ("paper", "real"):
            raise ValueError("live.mode فقط می‌تواند paper یا real باشد.")
