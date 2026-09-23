"""نگه‌داشتن آخرین پیام‌های گزارش در حافظه، برای نمایش در پنل."""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone


class LogBuffer(logging.Handler):
    def __init__(self, capacity: int = 500) -> None:
        super().__init__(level=logging.INFO)
        self.records: deque[dict] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._seq = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:  # پیام خراب نباید ربات را بکشد
            msg = str(record.msg)
        with self._lock:
            self._seq += 1
            self.records.append({
                "id": self._seq,
                "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="seconds"),
                "level": record.levelname.lower(),
                "message": msg,
            })

    def since(self, after_id: int = 0, limit: int = 200) -> list[dict]:
        with self._lock:
            items = [r for r in self.records if r["id"] > after_id]
        return items[-limit:]


LOG_BUFFER = LogBuffer()


def install() -> LogBuffer:
    logger = logging.getLogger("trading_bot")
    if LOG_BUFFER not in logger.handlers:
        logger.addHandler(LOG_BUFFER)
    if logger.level == logging.NOTSET or logger.level > logging.INFO:
        logger.setLevel(logging.INFO)
    return LOG_BUFFER
