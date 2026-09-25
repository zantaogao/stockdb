#!/bin/bash
# 启动交易API服务器（开盘前执行）
# 自动清理旧进程后启动

cd ~/.hermes/stockdb || exit 1

# 清理旧服务器进程
OLD_PID=$(lsof -ti :8081 2>/dev/null)
if [ -n "$OLD_PID" ]; then
    echo "Kill old server PID=$OLD_PID"
    kill -9 "$OLD_PID" 2>/dev/null
    sleep 1
fi

# 清理缓存
rm -rf core/__pycache__ agents/__pycache__ 2>/dev/null

# 启动新服务器
nohup python3 -B server_multi_account.py --port 8081 > /tmp/stockdb_server.log 2>&1 &

# 等待启动确认
sleep 2
if lsof -ti :8081 >/dev/null 2>&1; then
    echo "✅ Trading API server started on port 8081 (PID: $!)"
else
    echo "❌ Server failed to start, check /tmp/stockdb_server.log"
    tail -10 /tmp/stockdb_server.log
    exit 1
fi
