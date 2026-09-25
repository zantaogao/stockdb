#!/usr/bin/env python3
import duckdb
conn = duckdb.connect('tushare.db', read_only=True)

# 模糊搜索：名称含"杰"
print("=== 名称含'杰' ===")
rows = conn.execute("SELECT ts_code, name, industry, market, list_date FROM stock_basic WHERE name LIKE '%杰%' LIMIT 30").fetchall()
for r in rows:
    print(f"  {r[0]} {r[1]} 行业={r[2]} 市场={r[3]} 上市={r[4]}")

# 搜索代码 6882xx
print("\n=== 6882xx 段（可能科创板新上市） ===")
rows = conn.execute("SELECT ts_code, name, industry, market, list_date FROM stock_basic WHERE ts_code LIKE '6882%' ORDER BY list_date DESC LIMIT 20").fetchall()
for r in rows:
    print(f"  {r[0]} {r[1]} 行业={r[2]} 市场={r[3]} 上市={r[4]}")

conn.close()
