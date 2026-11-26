#!/bin/bash
IP=$(cat ~/coinbot.ip)
ssh -t -i ~/.ssh/id_rsa -o StrictHostKeyChecking=accept-new ubuntu@$IP '
mkdir -p ~/coinbot && cd ~/coinbot
echo; echo "==== 빗썸 새 키 입력 ===="
read -rp "Access Key 붙여넣고 엔터: " AK
read -rsp "Secret Key 붙여넣고 엔터 (화면에 안보임): " SK; echo
printf "BITHUMB_ACCESS_KEY=%s\nBITHUMB_SECRET_KEY=%s\n" "$AK" "$SK" > .env
chmod 600 .env; unset AK SK
echo "저장 완료 (길이: $(wc -c < .env) bytes)"
'
