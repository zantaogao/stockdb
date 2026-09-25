#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查 trade_log 实际数据分布"""
import sqlite3, os
BASE = os.path.expanduser('~/.hermes/stockdb')
s = sqlite3.connect(os.path.join(BASE, 'state.db'))

print("--- trade_log 表结构 ---")
cols = [r[1] for r in s.execute("PRAGMA table_info(trade_log)").fetchall()]
print("列:", cols)

print("\n--- direction 值分布 ---")
for r in s.execute("SELECT direction, COUNT(*) FROM trade_log GROUP BY 1").fetchall():
    print(f"  '{r[0]}': {r[1]} 笔")

print("\n--- strategy 值分布 ---")
for r in s.execute("SELECT strategy, COUNT(*) FROM trade_log GROUP BY 1").fetchall():
    print(f"  '{r[0]}': {r[1]} 笔")

print("\n--- 总行数 + 日期范围 ---")
print("总行数:", s.execute("SELECT COUNT(*) FROM trade_log").fetchone()[0])
r = s.execute("SELECT MIN(trade_date), MAX(trade_date) FROM trade_log").fetchone()
print(f"日期范围: {r[0]} ~ {r[1]}")

print("\n--- 最近 8 行样本 ---")
for r in s.execute("SELECT * FROM trade_log ORDER BY rowid DESC LIMIT 8").fetchall():
    print(" ", r)
s.close()
