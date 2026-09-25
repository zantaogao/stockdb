#!/usr/bin/env python3
"""检查下一个交易日"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.hermes' / 'stockdb'))

import duckdb

con = duckdb.connect(':memory:')
con.execute(f"ATTACH '{Path.home()}/.hermes/stockdb/tushare.db' AS tushare (READ_ONLY)")

# 查 20260721 之后的第一个交易日
next_day = con.execute(
    "SELECT MIN(trade_date) FROM tushare.daily WHERE trade_date > '20260721'"
).fetchone()[0]

# 查最新交易日
latest = con.execute(
    "SELECT MAX(trade_date) FROM tushare.daily"
).fetchone()[0]

# 查 20260720 是否有数据
july20_count = con.execute(
    "SELECT COUNT(*) FROM tushare.daily WHERE trade_date = '20260720'"
).fetchone()[0]

con.close()

print(f"Latest trading day: {latest}")
print(f"Next day after 20260721: {next_day}")
print(f"20260720 record count: {july20_count}")
