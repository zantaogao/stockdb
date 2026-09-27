#!/bin/bash
# 一次ssh拿全诊断: 进程/日志/exit
{
echo "==python进程=="
ps aux | grep -E "[t]rain_v6" || echo 无训练进程
echo "==日志=="
ls -la /mnt/c/Users/zantan/retrain_20260926/train_v6_c1.log 2>/dev/null
head -c 600 /mnt/c/Users/zantan/retrain_20260926/train_v6_c1.log 2>/dev/null || echo 日志不存在
echo "==尾=="
tail -c 300 /mnt/c/Users/zantan/retrain_20260926/train_v6_c1.log 2>/dev/null
} > /tmp/v6c1_diag.txt 2>&1
