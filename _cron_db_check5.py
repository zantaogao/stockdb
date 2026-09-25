#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确认 index_daily 是 view 还是表 + 评分链路数据流"""
import duckdb, os
BASE = os.path.expanduser('~/.hermes/stockdb')
conn = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)

print("--- information_schema.tables ---")
rows = conn.execute(
    "SELECT table_name, table_type FROM information_schema.tables WHERE table_name LIKE 'index%'").fetchall()
for r in rows:
    print(" ", r[0], "|", r[1])

# 若是 view，查 view 定义
try:
    v = conn.execute("SELECT sql FROM duckdb_views() WHERE view_name='index_daily'").fetchall()
    for r in v:
        print("\nview SQL:", r[0])
except Exception as e:
    print("duckdb_views 查询失败:", e)

# 对比两个表最近一行的值（000001.SH 8/13）
print("\n--- 000001.SH 8/13 两表对照 ---")
a = conn.execute("SELECT trade_date, close FROM index_daily_raw WHERE ts_code='000001.SH' AND trade_date='20260813'").fetchall()
b = conn.execute("SELECT CAST(date AS VARCHAR), close FROM index_daily WHERE index_code='000001.SH' AND date=DATE '2026-08-13'").fetchall()
print("raw: ", a)
print("旧表:", b)
conn.close()
