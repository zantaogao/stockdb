#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查 index_daily 相关表：是否双表、各自最新日期"""
import duckdb, os
BASE = os.path.expanduser('~/.hermes/stockdb')
conn = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)

tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
idx_tables = [t for t in tables if 'index' in t.lower()]
print("含 index 的表:", idx_tables)

for t in idx_tables:
    try:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        latest = conn.execute(f"SELECT MAX(trade_date) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} 行, MAX(trade_date)={latest}")
        # 最近 3 天逐日
        rows = conn.execute(
            f"SELECT trade_date, COUNT(*) FROM {t} WHERE trade_date >= '20260812' GROUP BY 1 ORDER BY 1").fetchall()
        print("    " + " ".join(f"{r[0]}:{r[1]}" for r in rows))
    except Exception as e:
        print(f"  {t}: ERROR {str(e)[:80]}")

# DESCRIBE 结构对比
print("\nindex_daily 结构:" if 'index_daily' in idx_tables else "")
if 'index_daily' in idx_tables:
    for r in conn.execute("DESCRIBE index_daily").fetchall():
        print("  ", r[0], r[1])
print("\nindex_daily_raw 结构:")
for r in conn.execute("DESCRIBE index_daily_raw").fetchall():
    print("  ", r[0], r[1])
conn.close()
