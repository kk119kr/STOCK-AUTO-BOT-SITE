#!/bin/bash
# 오라클 Cloud Shell 에서 실행: 무료 ARM 서버(2 OCPU, 12GB, Ubuntu 24.04) + 네트워크 만들기
set -e
C=$OCI_TENANCY
AD=$(oci iam availability-domain list -c $C --query 'data[0].name' --raw-output)
echo "[1/6] 네트워크(VCN)"
VCN=$(oci network vcn create -c $C --cidr-block 10.0.0.0/16 --display-name coinbot-vcn --wait-for-state AVAILABLE --query data.id --raw-output)
echo "[2/6] 인터넷 게이트웨이"
IGW=$(oci network internet-gateway create -c $C --vcn-id $VCN --is-enabled true --display-name coinbot-igw --wait-for-state AVAILABLE --query data.id --raw-output)
RT=$(oci network vcn get --vcn-id $VCN --query 'data."default-route-table-id"' --raw-output)
oci network route-table update --rt-id $RT --route-rules "[{\"cidrBlock\":\"0.0.0.0/0\",\"networkEntityId\":\"$IGW\"}]" --force > /dev/null
echo "[3/6] 공개 서브넷"
SN=$(oci network subnet create -c $C --vcn-id $VCN --cidr-block 10.0.0.0/24 --display-name coinbot-subnet --wait-for-state AVAILABLE --query data.id --raw-output)
echo "[4/6] 우분투 이미지"
IMG=$(oci compute image list -c $C --operating-system "Canonical Ubuntu" --operating-system-version "24.04" --shape VM.Standard.A1.Flex --sort-by TIMECREATED --query 'data[0].id' --raw-output)
[ -f ~/.ssh/id_ed25519 ] || ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -q
echo "[5/6] 서버 만들기 (1~3분)"
ID=$(oci compute instance launch -c $C --availability-domain $AD --shape VM.Standard.A1.Flex --shape-config '{"ocpus":2,"memoryInGBs":12}' --image-id $IMG --subnet-id $SN --assign-public-ip true --display-name coinbot --ssh-authorized-keys-file ~/.ssh/id_ed25519.pub --wait-for-state RUNNING --query data.id --raw-output)
echo "$ID" > ~/coinbot.id
echo "[6/6] 공인 IP"
IP=$(oci compute instance list-vnics --instance-id $ID --query 'data[0]."public-ip"' --raw-output)
echo "$IP" > ~/coinbot.ip
echo "=============================="
echo "PUBLIC_IP=$IP"
echo "=============================="
