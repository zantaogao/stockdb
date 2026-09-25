#!/bin/bash
# 独立启动数据重建（脱离Hermes进程树）
cd /Users/zantao/.hermes/stockdb
rm -f stock_clean.db stock_clean.db.wal
rm -rf stock_clean.db.tmp
/Library/Frameworks/Python.framework/Versions/3.11/bin/python3 rebuild_from_tdx.py > /tmp/rebuild_tdx_v2.log 2>&1
echo "EXIT_CODE=$?" >> /tmp/rebuild_tdx_v2.log
