#!/bin/bash
cd ~/.hermes/stockdb
rm -rf core/__pycache__ scripts/__pycache__ 2>/dev/null
nohup python3 -B server_multi_account.py --port 8081 > /tmp/stockdb_server.log 2>&1 &
echo "Started PID: $!"
