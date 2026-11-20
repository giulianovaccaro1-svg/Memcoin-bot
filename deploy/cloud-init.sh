#!/bin/bash
# =====================================================================
# Einrichtung des Papier-Bots auf einem Ubuntu-Server (läuft beim ersten Start automatisch)
# NUR diese zwei Zeilen anpassen (Telegram ist optional, aber nötig, um Meldungen zu sehen):
TELEGRAM_TOKEN="HIER_TOKEN_EINTRAGEN"
TELEGRAM_CHAT_ID="HIER_CHAT_ID_EINTRAGEN"
# =====================================================================
REPO="https://github.com/giulianovaccaro1-svg/Memcoin-bot.git"

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y git python3

id bot >/dev/null 2>&1 || useradd -m -s /bin/bash bot
if [ ! -d /home/bot/app ]; then
  sudo -u bot git clone --depth 1 "$REPO" /home/bot/app
fi

# Zugangsdaten nur für den Bot lesbar speichern
cat > /etc/memcoin-bot.env <<ENV
TELEGRAM_TOKEN=$TELEGRAM_TOKEN
TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID
ENV
chmod 600 /etc/memcoin-bot.env
chown bot:bot /etc/memcoin-bot.env

# Dauerdienst: startet nach Absturz und nach Neustart des Servers von allein.
# Vor jedem Start wird nur der Bot-Code (paper_bot.py) aktualisiert, nie dein Spielstand.
cat > /etc/systemd/system/memcoin-bot.service <<'SERVICE'
[Unit]
Description=Memecoin Papier-Bot
After=network-online.target
Wants=network-online.target

[Service]
User=bot
WorkingDirectory=/home/bot/app
EnvironmentFile=/etc/memcoin-bot.env
ExecStartPre=-/usr/bin/git -C /home/bot/app fetch -q origin main
ExecStartPre=-/usr/bin/git -C /home/bot/app checkout -q origin/main -- paper_bot.py
ExecStart=/usr/bin/python3 -u paper_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICE

# Täglicher Neustart um 04:00 UTC, damit Code-Updates automatisch übernommen werden
echo "0 4 * * * root systemctl restart memcoin-bot" > /etc/cron.d/memcoin-bot-restart

systemctl daemon-reload
systemctl enable --now memcoin-bot
