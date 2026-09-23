#!/usr/bin/env bash
# ============================================================
#  نصب ربات طلا روی Ubuntu 24.04 (یا 22.04) — با یک دستور
#
#    cd ~/My_Traid_prg
#    sudo bash deploy/install.sh
#
#  کارهایی که می‌کند:
#    ۱. پایتون و ابزارهای لازم را نصب می‌کند
#    ۲. محیط مجازی (.venv) می‌سازد و برنامه را نصب می‌کند
#    ۳. فایل .env را با یک رمز تصادفی برای پنل می‌سازد
#    ۴. سرویس systemd «goldbot» را می‌سازد تا پنل و ربات ۲۴ ساعته
#       روشن بمانند و بعد از ری‌استارت سرور خودکار بالا بیایند
# ============================================================
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "❌ با sudo اجرا کن:  sudo bash deploy/install.sh"; exit 1
fi

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="${SUDO_USER:-root}"
SERVICE=goldbot
PORT="${PANEL_PORT:-8000}"

echo "▶ پوشه برنامه: $APP_DIR   |   کاربر اجرا: $RUN_USER"

echo "▶ ۱/۴ نصب بسته‌های سیستم…"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv python3-pip git curl >/dev/null

echo "▶ ۲/۴ ساخت محیط مجازی و نصب برنامه… (چند دقیقه طول می‌کشد)"
sudo -u "$RUN_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$RUN_USER" "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u "$RUN_USER" "$APP_DIR/.venv/bin/pip" install -q -e "$APP_DIR"
sudo -u "$RUN_USER" mkdir -p "$APP_DIR/data/cache"

echo "▶ ۳/۴ تنظیم رمز پنل…"
ENV_FILE="$APP_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  sudo -u "$RUN_USER" cp "$APP_DIR/.env.example" "$ENV_FILE"
fi
if ! grep -qE '^PANEL_PASSWORD=.{8,}' "$ENV_FILE"; then
  PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')"
  if grep -q '^PANEL_PASSWORD=' "$ENV_FILE"; then
    sed -i "s|^PANEL_PASSWORD=.*|PANEL_PASSWORD=$PASSWORD|" "$ENV_FILE"
  else
    echo "PANEL_PASSWORD=$PASSWORD" >> "$ENV_FILE"
  fi
  NEW_PASSWORD="$PASSWORD"
fi
chmod 600 "$ENV_FILE"
chown "$RUN_USER" "$ENV_FILE"

echo "▶ ۴/۴ ساخت سرویس systemd…"
cat > "/etc/systemd/system/$SERVICE.service" <<UNIT
[Unit]
Description=Gold trading bot (paper) + web panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python -m trading_bot web --port $PORT
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
# محدودیت‌ها — روی سرور ۴ گیگابایتی جای کافی برای بقیه می‌ماند
MemoryMax=1500M
CPUQuota=150%
# امنیت
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectKernelTunables=true
ProtectControlGroups=true

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now "$SERVICE" >/dev/null
sleep 3

if systemctl is-active --quiet "$SERVICE"; then
  echo ""
  echo "✅ نصب شد و سرویس روشن است."
else
  echo "❌ سرویس بالا نیامد. گزارش خطا:"
  journalctl -u "$SERVICE" -n 30 --no-pager
  exit 1
fi

IP="$(curl -s -4 --max-time 5 https://api.ipify.org || hostname -I | awk '{print $1}')"
cat <<INFO

────────────────────────────────────────────────────────
 پنل روی خود سرور و پورت $PORT بالا است (فقط 127.0.0.1 — امن).

 برای باز کردنش، روی کامپیوتر خودت (نه سرور) این را بزن:

     ssh -L $PORT:127.0.0.1:$PORT $RUN_USER@$IP

 و تا وقتی آن ترمینال باز است، در مرورگر برو به:

     http://localhost:$PORT
INFO
if [[ -n "${NEW_PASSWORD:-}" ]]; then
  echo ""
  echo " رمز پنل:  $NEW_PASSWORD"
  echo " (در فایل $ENV_FILE هم ذخیره است)"
fi
cat <<INFO

 دستورهای مفید:
     sudo systemctl status $SERVICE       وضعیت
     sudo systemctl restart $SERVICE      ری‌استارت
     sudo journalctl -u $SERVICE -f       گزارش زنده
     sudo bash deploy/update.sh           به‌روزرسانی از گیت‌هاب
────────────────────────────────────────────────────────
INFO
