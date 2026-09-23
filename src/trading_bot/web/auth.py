"""ورود به پنل — یک رمز عبور، نشست امضاشده، و محدودیت تلاش.

پنل روی اینترنت است؛ کسی که واردش شود می‌تواند ربات را خاموش/روشن کند و
تنظیمات را عوض کند. پس:
  - رمز از متغیر محیطی PANEL_PASSWORD (فایل .env) خوانده می‌شود، نه از کد.
  - بعد از ۵ تلاش ناموفق از یک IP، آن IP برای ۱۵ دقیقه قفل می‌شود.
  - کوکی نشست HttpOnly و SameSite=Strict است (جاوااسکریپت و سایت‌های دیگر
    به آن دسترسی ندارند) و ۷ روز اعتبار دارد.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from pathlib import Path

SESSION_COOKIE = "gold_session"
SESSION_TTL = 7 * 24 * 3600
MAX_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60
MIN_PASSWORD_LENGTH = 8


def load_env_file(path: str | Path = ".env") -> None:
    """خواندن ساده فایل .env (بدون وابستگی اضافه). متغیرهای موجود را بازنویسی نمی‌کند."""
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def load_secret(path: str | Path = "data/.panel_secret") -> bytes:
    """کلید امضای نشست. اگر نبود، یک کلید تصادفی می‌سازد و ذخیره می‌کند."""
    if os.environ.get("PANEL_SECRET"):
        return os.environ["PANEL_SECRET"].encode()
    path = Path(path)
    if path.exists():
        return path.read_bytes().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32).encode()
    path.write_bytes(key)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


class Auth:
    def __init__(self, password: str, secret: bytes) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"رمز پنل باید حداقل {MIN_PASSWORD_LENGTH} حرف باشد.\n"
                "در فایل .env بنویس:  PANEL_PASSWORD=یک-رمز-طولانی-و-سخت"
            )
        self._password = password.encode()
        self._secret = secret
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    # ── رمز عبور و قفل IP

    def locked_for(self, ip: str) -> int:
        """چند ثانیه دیگر این IP قفل است (۰ یعنی آزاد)."""
        now = time.time()
        with self._lock:
            recent = [t for t in self._failures.get(ip, []) if now - t < LOCKOUT_SECONDS]
            self._failures[ip] = recent
            if len(recent) >= MAX_FAILURES:
                return int(LOCKOUT_SECONDS - (now - recent[0])) + 1
        return 0

    def check_password(self, ip: str, password: str) -> bool:
        ok = hmac.compare_digest(password.encode(), self._password)
        if ok:
            with self._lock:
                self._failures.pop(ip, None)
        else:
            with self._lock:
                self._failures.setdefault(ip, []).append(time.time())
        return ok

    # ── نشست

    def _sign(self, payload: bytes) -> str:
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def issue(self) -> str:
        expires = str(int(time.time()) + SESSION_TTL).encode()
        payload = base64.urlsafe_b64encode(expires).decode()
        return f"{payload}.{self._sign(expires)}"

    def verify(self, token: str | None) -> bool:
        if not token or "." not in token:
            return False
        payload, signature = token.rsplit(".", 1)
        try:
            expires = base64.urlsafe_b64decode(payload.encode())
        except (ValueError, TypeError):
            return False
        if not hmac.compare_digest(signature, self._sign(expires)):
            return False
        try:
            return int(expires) > time.time()
        except ValueError:
            return False
