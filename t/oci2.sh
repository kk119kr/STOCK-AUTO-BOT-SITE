#!/bin/bash
# 이어서: 이미 만든 coinbot-vcn/subnet 을 써서 서버 만들기 (RSA 키)
set -e
C=$OCI_TENANCY
AD=$(oci iam availability-domain list -c $C --query 'data[0].name' --raw-output)
SN=$(oci network subnet list -c $C --display-name coinbot-subnet --query 'data[0].id' --raw-output)
IMG=$(oci compute image list -c $C --operating-system "Canonical Ubuntu" --operating-system-version "24.04" --shape VM.Standard.A1.Flex --sort-by TIMECREATED --query 'data[0].id' --raw-output)
[ -f ~/.ssh/id_rsa ] || ssh-keygen -t rsa -b 4096 -N "" -f ~/.ssh/id_rsa -q
echo "[5/6] 서버 만들기 (1~3분)"
ID=$(oci compute instance launch -c $C --availability-domain $AD --shape VM.Standard.A1.Flex --shape-config '{"ocpus":2,"memoryInGBs":12}' --image-id $IMG --subnet-id $SN --assign-public-ip true --display-name coinbot --ssh-authorized-keys-file ~/.ssh/id_rsa.pub --wait-for-state RUNNING --query data.id --raw-output)
echo "$ID" > ~/coinbot.id
echo "[6/6] 공인 IP"
IP=$(oci compute instance list-vnics --instance-id $ID --query 'data[0]."public-ip"' --raw-output)
echo "$IP" > ~/coinbot.ip
echo "=============================="
echo "PUBLIC_IP=$IP"
echo "=============================="
