#!/bin/bash
ID=$(cat ~/coinbot.id)
oci compute instance get --instance-id $ID --query 'data.{shape:shape,state:"lifecycle-state",cpu:"shape-config".ocpus,mem:"shape-config"."memory-in-gbs"}' --output table
IP=$(oci compute instance list-vnics --instance-id $ID --query 'data[0]."public-ip"' --raw-output)
echo "$IP" > ~/coinbot.ip
echo "PUBLIC_IP=$IP"
