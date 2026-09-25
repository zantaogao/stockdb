#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""排查：index_daily_raw 缺 8/14 + state.db signal_history 列结构"""
import duckdb, sqlite3, os

BASE = os.path.expanduser('~/.hermes/stockdb')
TD = os.path.join(BASE, 'tushare.db')
SD = os.path.join(BASE, 'state.db')

print("--- index_daily_raw 最近 12 天逐日 ---")
conn = duckdb.connect(TD, read_only=True)
rows = conn.execute(
    "SELECT trade_date, COUNT(DISTINCT ts_code) n, COUNT(*) total "
    "FROM index_daily_raw WHERE trade_date >= '20260801' GROUP BY 1 ORDER BY 1").fetchall()
for r in rows:
    print(f"  {r[0]}: {r[1]} 指数, {r[2]} 行")
# 8/14 到底有没有任何行
n = conn.execute("SELECT COUNT(*) FROM index_daily_raw WHERE trade_date='20260814'").fetchone()[0]
print(f"  8/14 行数: {n}")
# 指数列表对比
print("  8/13 指数: ", [r[0] for r in conn.execute(
    "SELECT DISTINCT ts_code FROM index_daily_raw WHERE trade_date='20260813' ORDER BY 1").fetchall()])
print("  8/14 指数: ", [r[0] for r in conn.execute(
    "SELECT DISTINCT ts_code FROM index_daily_raw WHERE trade_date='20260814' ORDER BY 1").fetchall()])
conn.close()

print("\n--- state.db signal_history 结构 ---")
s = sqlite3.connect(SD)
cols = [r[1] for r in s.execute("PRAGMA table_info(signal_history)").fetchall()]
print("  列: ", cols)
print("  行数: ", s.execute("SELECT COUNT(*) FROM signal_history").fetchone()[0])
rows = s.execute("SELECT * FROM signal_history LIMIT 2").fetchall()
print("  示例行: ", rows)
s.close()
