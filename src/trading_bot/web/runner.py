"""اجرای ربات در پس‌زمینه پنل.

ربات در یک thread جدا داخل همان پروسه پنل اجرا می‌شود؛ پس فقط یک سرویس
روی سرور لازم است. اگر سرور ری‌استارت شود و ربات قبلاً روشن بوده، خودکار
دوباره روشن می‌شود (وضعیت در data/bot_runtime.json ذخیره می‌شود).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from ..broker import PaperBroker
from ..config import Config
from ..live import LiveTrader

log = logging.getLogger("trading_bot.runner")


class BotRunner:
    def __init__(self, config_path: str | Path, runtime_file: str | Path = "data/bot_runtime.json") -> None:
        self.config_path = Path(config_path)
        self.runtime_file = Path(runtime_file)
        self.trader: LiveTrader | None = None
        self.thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def load_config(self) -> Config:
        return Config.load(self.config_path)

    # ── وضعیت

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def broker(self, cfg: Config | None = None) -> PaperBroker:
        """بروکر فعلی (اگر ربات روشن است همان، وگرنه از روی فایل)."""
        if self.running and self.trader:
            return self.trader.broker
        cfg = cfg or self.load_config()
        return PaperBroker(
            initial_capital=cfg.risk.initial_capital,
            fee_rate=cfg.costs.fee_rate,
            slippage_rate=cfg.costs.slippage_rate,
            state_file=cfg.live.state_file,
        )

    @property
    def last_status(self) -> dict[str, Any]:
        return dict(self.trader.status) if self.trader else {}

    def _remember(self, should_run: bool) -> None:
        self.runtime_file.parent.mkdir(parents=True, exist_ok=True)
        self.runtime_file.write_text(json.dumps({"should_run": should_run}), encoding="utf-8")

    def _should_run(self) -> bool:
        if not self.runtime_file.exists():
            return False
        try:
            return bool(json.loads(self.runtime_file.read_text(encoding="utf-8")).get("should_run"))
        except (ValueError, OSError):
            return False

    # ── فرمان‌ها

    def start(self) -> None:
        with self._lock:
            if self.running:
                raise RuntimeError("ربات همین الان روشن است.")
            cfg = self.load_config()
            trader = LiveTrader(cfg)
            if trader.broker.state.halted:
                raise RuntimeError(
                    "کلید قطع اضطراری زده شده (افت سرمایه از حد مجاز گذشته بود). "
                    "اول نتیجه را بررسی کن، بعد حساب را ریست کن."
                )
            self.trader = trader
            self.thread = threading.Thread(target=self._run, name="paper-bot", daemon=True)
            self.thread.start()
            self._remember(True)

    def _run(self) -> None:
        assert self.trader is not None
        try:
            self.trader.run()
        except Exception:  # هر خطای پیش‌بینی‌نشده باید در گزارش دیده شود
            log.exception("ربات با خطای غیرمنتظره متوقف شد")
        if self.trader.broker.state.halted:
            self._remember(False)

    def stop(self, remember: bool = True) -> None:
        with self._lock:
            if self.trader:
                self.trader.stop_event.set()
            if self.thread:
                self.thread.join(timeout=30)
            if remember:
                self._remember(False)

    def restart_if_running(self) -> bool:
        """بعد از تغییر تنظیمات: اگر روشن بود، با تنظیمات تازه دوباره روشن می‌شود."""
        with self._lock:
            if not self.running:
                return False
            self.stop(remember=False)
            self.start()
            return True

    def reset(self) -> None:
        with self._lock:
            if self.running:
                raise RuntimeError("اول ربات را خاموش کن، بعد حساب را ریست کن.")
            cfg = self.load_config()
            self.broker(cfg).reset(cfg.risk.initial_capital)
            self.trader = None
            log.info("حساب کاغذی با سرمایه %.2f ریست شد.", cfg.risk.initial_capital)

    def close_position(self, price: float) -> None:
        with self._lock:
            if self.running and self.trader:
                self.trader.close_position(price)
                return
            broker = self.broker()
            if not broker.state.in_position:
                raise ValueError("پوزیشن بازی وجود ندارد.")
            broker.sell(self.load_config().market.symbol, broker.state.position_qty, price, reason="manual")
            log.info("پوزیشن به‌صورت دستی بسته شد در قیمت %.2f", price)

    def resume_if_needed(self) -> None:
        if self._should_run() and not self.running:
            try:
                self.start()
                log.info("ربات بعد از راه‌اندازی مجدد سرور، خودکار روشن شد.")
            except Exception as exc:
                log.error("روشن کردن خودکار ربات ناموفق بود: %s", exc)
