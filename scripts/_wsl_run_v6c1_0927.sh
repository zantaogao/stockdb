#!/bin/bash
# v6_c1训练 spawn（WSL root 身份，脱离 ssh 会话）
cd /mnt/c/Users/zantan/retrain_20260926
rm -f train_v6_c1.log
setsid nohup /usr/bin/python3 train_v6_c1.py > train_v6_c1.log 2>&1 < /dev/null &
echo "SPAWNED_PID=$!"
