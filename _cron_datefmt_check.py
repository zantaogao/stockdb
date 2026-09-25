#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查 fusion_3f_signals / signal_history 日期格式分布 + 跨表 JOIN 代码"""
import sqlite3, os, subprocess
BASE = os.path.expanduser('~/.hermes/stockdb')
s = sqlite3.connect(os.path.join(BASE, 'state.db'))

print("--- fusion_3f_signals.date 格式分布 ---")
rows = s.execute("SELECT date, COUNT(*) FROM fusion_3f_signals GROUP BY 1 ORDER BY 1 DESC LIMIT 10").fetchall()
for r in rows:
    print(f"  '{r[0]}': {r[1]}")

print("\n--- fusion_3f_signals 最新 5 个日期(按原始串排序) ---")
for r in s.execute("SELECT DISTINCT date FROM fusion_3f_signals ORDER BY date DESC LIMIT 5").fetchall():
    print(f"  '{r[0]}'")

print("\n--- signal_history.date 格式分布 ---")
rows = s.execute("SELECT date, COUNT(*) FROM signal_history GROUP BY 1 ORDER BY 1 DESC LIMIT 10").fetchall()
for r in rows:
    print(f"  '{r[0]}': {r[1]}")

print("\n--- 两表日期格式对比（同一天两种格式各多少） ---")
for fmt, tbl in [('YYYY-MM-DD', 'fusion_3f_signals'), ('YYYYMMDD', 'fusion_3f_signals')]:
    pass
# 统计各表带连字符 vs 不带
for tbl in ['fusion_3f_signals', 'signal_history']:
    h = s.execute(f"SELECT COUNT(*) FROM {tbl} WHERE date LIKE '%-%'").fetchone()[0]
    n = s.execute(f"SELECT COUNT(*) FROM {tbl} WHERE date NOT LIKE '%-%'").fetchone()[0]
    print(f"  {tbl}: 带连字符 {h} 行 / 不带 {n} 行")

print("\n--- 跨表 JOIN 代码搜索 ---")
out = subprocess.run(
    ['grep', '-rn', 'fusion_3f_signals', '--include=*.py', '.'],
    capture_output=True, text=True, cwd=BASE)
lines = [l for l in out.stdout.splitlines() if 'JOIN' in l or ('signal_history' in l and 'fusion' in l.lower())]
for l in lines[:20]:
    print(" ", l[:150])
s.close()
