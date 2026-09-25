#!/usr/bin/env python3
"""检查 daily 表最新日期"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.hermes' / 'stockdb'))

import duckdb

# 用临时内存数据库 attach tushare.db 只读
con = duckdb.connect(':memory:')
con.execute(f"ATTACH '{Path.home()}/.hermes/stockdb/tushare.db' AS tushare (READ_ONLY)")

# 查最新日期
latest = con.execute(
    "SELECT MAX(trade_date) FROM tushare.daily WHERE ts_code LIKE '%.SZ' OR ts_code LIKE '%.SH'"
).fetchone()[0]

# 查最近 10 个日期
dates = con.execute(
    "SELECT DISTINCT trade_date FROM tushare.daily "
    "WHERE ts_code LIKE '%.SZ' OR ts_code LIKE '%.SH' "
    "ORDER BY trade_date DESC LIMIT 10"
).fetchall()

# 查 20260721 是否有数据
july21 = con.execute(
    "SELECT COUNT(*) FROM tushare.daily WHERE trade_date = 20260721"
).fetchone()[0]

con.close()

print(f"Latest daily date: {latest}")
print(f"Recent dates: {[str(d[0]) for d in dates]}")
print(f"20260721 record count: {july21}")
