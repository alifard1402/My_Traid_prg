#!/usr/bin/env bash
# به‌روزرسانی ربات از گیت‌هاب — وضعیت حساب و تنظیمات پنل (پوشه data/) دست نمی‌خورد.
#    sudo bash deploy/update.sh
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="${SUDO_USER:-root}"
cd "$APP_DIR"
echo "▶ گرفتن آخرین نسخه…"
sudo -u "$RUN_USER" git pull --ff-only
echo "▶ نصب وابستگی‌ها…"
sudo -u "$RUN_USER" "$APP_DIR/.venv/bin/pip" install -q -e "$APP_DIR"
echo "▶ ری‌استارت سرویس…"
systemctl restart goldbot
sleep 2
systemctl is-active --quiet goldbot && echo "✅ به‌روز شد." || { journalctl -u goldbot -n 30 --no-pager; exit 1; }
