#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""index_daily 旧表（评分链路用）最新状态 + 写入方排查"""
import duckdb, os, subprocess
BASE = os.path.expanduser('~/.hermes/stockdb')
conn = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)

print("--- index_daily 旧表（index_code/date 结构）---")
n = conn.execute("SELECT COUNT(*) FROM index_daily").fetchone()[0]
print(f"总行数: {n}")
rows = conn.execute(
    "SELECT CAST(date AS VARCHAR) d, COUNT(*) FROM index_daily WHERE date >= DATE '2026-08-01' GROUP BY 1 ORDER BY 1").fetchall()
print("最近日期逐日:", " ".join(f"{r[0]}:{r[1]}" for r in rows))
latest = conn.execute("SELECT MAX(date) FROM index_daily").fetchone()[0]
print(f"MAX(date): {latest}")

# 8/14 有没有数据
c = conn.execute("SELECT COUNT(*) FROM index_daily WHERE date >= DATE '2026-08-14'").fetchone()[0]
print(f"date >= 2026-08-14 行数: {c}")
conn.close()

print("\n--- 写入方排查 ---")
out = subprocess.run(['grep', '-rn', 'INTO index_daily', 'scripts/', 'core/', 'agents/'],
                     capture_output=True, text=True, cwd=BASE)
print(out.stdout or "无 INTO index_daily 写入")
out2 = subprocess.run(['grep', '-rn', 'index_daily', 'scripts/', 'core/', 'agents/'],
                      capture_output=True, text=True, cwd=BASE)
lines = [l for l in out2.stdout.splitlines() if 'raw' not in l and 'index_daily(' not in l]
for l in lines[:30]:
    print(l)
