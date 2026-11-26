#!/bin/bash
# 서버 만들기 재시도: ARM(2 OCPU/12GB) 을 1분 간격으로 최대 15번, 안 되면 무료 AMD 마이크로로
C=$OCI_TENANCY
AD=$(oci iam availability-domain list -c $C --query 'data[0].name' --raw-output)
SN=$(oci network subnet list -c $C --display-name coinbot-subnet --query 'data[0].id' --raw-output)
[ -f ~/.ssh/id_rsa ] || ssh-keygen -t rsa -b 4096 -N "" -f ~/.ssh/id_rsa -q
IMGA=$(oci compute image list -c $C --operating-system "Canonical Ubuntu" --operating-system-version "24.04" --shape VM.Standard.A1.Flex --sort-by TIMECREATED --query 'data[0].id' --raw-output)
ID=""
for i in $(seq 1 15); do
  echo "ARM 시도 $i/15 $(date +%H:%M:%S)"
  OUT=$(oci compute instance launch -c $C --availability-domain $AD --shape VM.Standard.A1.Flex --shape-config '{"ocpus":2,"memoryInGBs":12}' --image-id $IMGA --subnet-id $SN --assign-public-ip true --display-name coinbot --ssh-authorized-keys-file ~/.ssh/id_rsa.pub --max-retries 0 --query data.id --raw-output 2>&1) && { ID="$OUT"; break; }
  echo "$OUT" | grep -o '"message": "[^"]*"' | head -1
  sleep 60
done
if [ -z "$ID" ]; then
  echo "ARM 자리가 없어 무료 AMD 마이크로(1GB)로 만듭니다"
  IMGX=$(oci compute image list -c $C --operating-system "Canonical Ubuntu" --operating-system-version "24.04" --shape VM.Standard.E2.1.Micro --sort-by TIMECREATED --query 'data[0].id' --raw-output)
  ID=$(oci compute instance launch -c $C --availability-domain $AD --shape VM.Standard.E2.1.Micro --image-id $IMGX --subnet-id $SN --assign-public-ip true --display-name coinbot --ssh-authorized-keys-file ~/.ssh/id_rsa.pub --query data.id --raw-output)
fi
echo "$ID" > ~/coinbot.id
echo "켜지는 중..."
oci compute instance get --instance-id $ID --wait-for-state RUNNING --query 'data."shape"' --raw-output
IP=$(oci compute instance list-vnics --instance-id $ID --query 'data[0]."public-ip"' --raw-output)
echo "$IP" > ~/coinbot.ip
echo "=============================="
echo "PUBLIC_IP=$IP"
echo "=============================="
