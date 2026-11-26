#!/bin/bash
set -e
cd ~/coinbot
if ! swapon --show | grep -q swapfile; then sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile && echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null; fi
echo "[1/3] 스왑 OK"
command -v node >/dev/null || { curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - >/dev/null && sudo apt-get install -y nodejs >/dev/null; }
command -v claude >/dev/null || sudo npm install -g @anthropic-ai/claude-code >/dev/null
echo "[2/3] Claude Code OK: $(claude --version)"
curl -fsSL https://raw.githubusercontent.com/kk119kr/stock-auto-bot-site/b48cd6a83728e4e4023e8bac25d5c56030118083/t/coinbot.py -o coinbot.py.new
python3 -c "import ast;ast.parse(open('coinbot.py.new').read())"
cp coinbot.py coinbot.py.bak; mv coinbot.py.new coinbot.py
echo "[3/3] 새 봇 코드 설치 OK (재시작 전)"
