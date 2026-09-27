#!/bin/bash
# v8 三链训练 spawn（WSL root，脱离 ssh 会话，同 v6_c1 成功模式）
cd /mnt/c/Users/zantan/retrain_20260927
rm -f train_v8.log
setsid nohup /usr/bin/python3 train_v8.py > train_v8.log 2>&1 < /dev/null &
echo "SPAWNED_PID=$!"
