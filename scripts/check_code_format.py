#!/usr/bin/env python3
"""检查 daily 表 ts_code 格式"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.hermes' / 'stockdb'))

import duckdb

con = duckdb.connect(':memory:')
con.execute(f"ATTACH '{Path.home()}/.hermes/stockdb/tushare.db' AS tushare (READ_ONLY)")

# 查 20260721 的 ts_code 格式
sample = con.execute(
    "SELECT ts_code FROM tushare.daily WHERE trade_date = 20260721 LIMIT 10"
).fetchall()

# 查有多少只股票
total = con.execute(
    "SELECT COUNT(DISTINCT ts_code) FROM tushare.daily WHERE trade_date = 20260721"
).fetchone()[0]

# 查 state.db 中 20260721 的股票代码格式
import sqlite3
state = sqlite3.connect(str(Path.home() / '.hermes' / 'stockdb' / 'state.db'))
state_codes = state.execute(
    "SELECT DISTINCT stock_code FROM signal_history WHERE date = 20260721 LIMIT 10"
).fetchall()
state_total = state.execute(
    "SELECT COUNT(DISTINCT stock_code) FROM signal_history WHERE date = 20260721"
).fetchone()[0]
state.close()

con.close()

print("tushare.db daily 20260721 ts_code 样例:")
for r in sample:
    print(f"  {r[0]}")
print(f"总数：{total}只")

print("\nstate.db signal_history 20260721 stock_code 样例:")
for r in state_codes:
    print(f"  {r[0]}")
print(f"总数：{state_total}只")
