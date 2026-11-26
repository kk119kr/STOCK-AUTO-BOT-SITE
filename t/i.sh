#!/bin/bash
set -e
H=$(dirname "$0")
cp "$H/coinbot.py" ~/coinbot/coinbot.py
sudo tee /etc/systemd/system/coinbot.service >/dev/null <<'UNIT'
[Unit]
Description=Bithumb 24h coin bot
After=network-online.target
Wants=network-online.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/coinbot
ExecStartPre=-/usr/bin/pkill -f bot1h.py
ExecStart=/usr/bin/python3 -u /home/ubuntu/coinbot/coinbot.py
Restart=always
RestartSec=30
StandardOutput=append:/home/ubuntu/coinbot/run.log
StandardError=append:/home/ubuntu/coinbot/run.log

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
python3 -m py_compile ~/coinbot/coinbot.py
clear; echo "xxxxxxxx 설치 완료 (아직 안 켜짐)"
