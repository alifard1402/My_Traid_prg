"""خواندن و اعتبارسنجی فایل تنظیمات.

تنظیمات از دو جا خوانده می‌شود:
  ۱. config.yaml                 ← مقادیر پایه (با توضیح فارسی کنار هر خط)
  ۲. data/panel_settings.json    ← تغییراتی که از پنل وب ذخیره شده

فایل دوم روی اولی «می‌نشیند». این‌طوری پنل هیچ‌وقت config.yaml و
توضیحاتش را خراب نمی‌کند؛ برای برگشتن به تنظیمات پایه کافی است فایل
دوم را پاک کنی (یا در پنل دکمه «بازگشت به پیش‌فرض» را بزنی).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")

#: بخش‌هایی که از پنل قابل تغییرند (panel خودش عمداً نیست)
EDITABLE_SECTIONS = ("market", "strategy", "risk", "costs", "live")


@dataclass
class MarketConfig:
    symbol: str = "XAUUSD"
    timeframe: str = "4h"
    source: str = "auto"


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
    fee_rate: float = 0.002
    slippage_rate: float = 0.0005


@dataclass
class LiveConfig:
    mode: str = "paper"
    poll_seconds: int = 60
    state_file: str = "data/paper_state.json"


@dataclass
class PanelConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    settings_file: str = "data/panel_settings.json"


def deep_merge(base: dict, extra: dict) -> dict:
    """دیکشنری extra را روی base می‌نشاند (تو در تو)."""
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


@dataclass
class Config:
    market: MarketConfig = field(default_factory=MarketConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    costs: CostConfig = field(default_factory=CostConfig)
    live: LiveConfig = field(default_factory=LiveConfig)
    panel: PanelConfig = field(default_factory=PanelConfig)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Config":
        cfg = cls(
            market=MarketConfig(**raw.get("market", {})),
            strategy=StrategyConfig(**raw.get("strategy", {})),
            risk=RiskConfig(**raw.get("risk", {})),
            costs=CostConfig(**raw.get("costs", {})),
            live=LiveConfig(**raw.get("live", {})),
            panel=PanelConfig(**raw.get("panel", {})),
        )
        cfg.validate()
        return cfg

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONFIG_PATH, use_overrides: bool = True) -> "Config":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"فایل تنظیمات پیدا نشد: {path}\n"
                "از ریشه پروژه اجرا کن، یا با --config مسیرش را بده."
            )
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if use_overrides:
            settings_file = Path(PanelConfig(**raw.get("panel", {})).settings_file)
            if settings_file.exists():
                overrides = json.loads(settings_file.read_text(encoding="utf-8"))
                overrides = {k: v for k, v in overrides.items() if k in EDITABLE_SECTIONS}
                raw = deep_merge(raw, overrides)
                # پارامترهای استراتژی جایگزین می‌شوند، نه ادغام (استراتژی‌ها پارامتر مشترک ندارند)
                if "params" in overrides.get("strategy", {}):
                    raw["strategy"]["params"] = overrides["strategy"]["params"]
        return cls.from_dict(raw)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        if not 0 < self.risk.risk_per_trade <= 0.1:
            raise ValueError(
                "risk_per_trade باید بین ۰ و ۰.۱ باشد. "
                "ریسک بیش از ۱۰٪ در هر معامله یعنی نابودی حساب."
            )
        if not 0 < self.risk.max_position_pct <= 1.0:
            raise ValueError("max_position_pct باید بین ۰ و ۱ باشد (بدون اهرم).")
        if not 0 < self.risk.max_drawdown_stop < 1.0:
            raise ValueError("max_drawdown_stop باید بین ۰ و ۱ باشد.")
        if self.risk.initial_capital <= 0:
            raise ValueError("initial_capital باید مثبت باشد.")
        if not 0 <= self.costs.fee_rate < 0.05 or not 0 <= self.costs.slippage_rate < 0.05:
            raise ValueError("کارمزد و لغزش باید عددی کوچک و نامنفی باشند (مثلاً 0.002).")
        if self.live.mode not in ("paper", "real"):
            raise ValueError("live.mode فقط می‌تواند paper یا real باشد.")
        if self.live.poll_seconds < 5:
            raise ValueError("poll_seconds حداقل ۵ ثانیه است (صرافی‌ها درخواست زیاد را مسدود می‌کنند).")


def save_overrides(cfg: Config, changes: dict[str, Any]) -> Config:
    """تغییرات پنل را اعتبارسنجی و در فایل جداگانه ذخیره می‌کند.

    اول تنظیمات جدید را می‌سازد و validate می‌کند؛ فقط اگر معتبر بود ذخیره
    می‌شود. پس تنظیم غلط هیچ‌وقت روی دیسک نمی‌نشیند.
    """
    changes = {k: v for k, v in changes.items() if k in EDITABLE_SECTIONS}
    path = Path(cfg.panel.settings_file)
    existing: dict[str, Any] = {}
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))

    # پارامترهای استراتژی را کامل جایگزین می‌کنیم، نه ادغام — وگرنه با
    # عوض کردن استراتژی، پارامترهای استراتژی قبلی باقی می‌مانند.
    merged = deep_merge(existing, changes)
    combined = deep_merge(cfg.to_dict(), merged)
    if "params" in changes.get("strategy", {}):
        merged["strategy"]["params"] = changes["strategy"]["params"]
        combined["strategy"]["params"] = changes["strategy"]["params"]

    new_cfg = Config.from_dict(combined)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    return new_cfg


def clear_overrides(cfg: Config) -> None:
    path = Path(cfg.panel.settings_file)
    if path.exists():
        path.unlink()
