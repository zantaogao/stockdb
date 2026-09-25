#!/bin/bash
cd ~/.hermes/stockdb
rm -rf core/__pycache__ scripts/__pycache__ 2>/dev/null
PYTHONUNBUFFERED=1 python3 server_multi_account.py --port 8081
