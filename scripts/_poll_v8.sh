#!/bin/bash
# 查 v8 训练进程（v6_c1 成功模式：python 子进程在 Windows 侧 tasklist 可见）
echo "=== Windows 侧 python 进程 ==="
tasklist /FO CSV 2>/dev/null | grep -i python | head -5
echo "=== WSL 侧 python 进程 ==="
ps -eo pid,etime,rss,args 2>/dev/null | grep [p]ython | grep -v grep | head -5
echo "=== out/ ==="
ls -la /mnt/c/Users/zantan/retrain_20260927/out/ 2>/dev/null | head -8
echo "=== log ==="
wc -c /mnt/c/Users/zantan/retrain_20260927/train_v8.log 2>/dev/null
