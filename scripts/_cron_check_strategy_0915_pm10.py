#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cron 监督 09-15 补充：trade_log 日期格式分布 + 冷却表状态"""
import sqlite3, os

c = sqlite3.connect(os.path.expanduser('~/.hermes/stockdb/ledger.db'))
print("=== trade_log 最近25行 (id, date, time, strategy, direction, code) ===")
for r in c.execute("SELECT id, trade_date, trade_time, strategy, direction, code FROM trade_log ORDER BY id DESC LIMIT 25"):
    print("  ", r)

print("\n=== trade_log 日期格式分布（近10个日期值） ===")
for r in c.execute("SELECT trade_date, COUNT(*) FROM trade_log GROUP BY 1 ORDER BY 1 DESC LIMIT 10"):
    print("  ", r)

print("\n=== trade_cooldown ===")
cols = [r[1] for r in c.execute("PRAGMA table_info(trade_cooldown)")]
print("cols:", cols)
for r in c.execute("SELECT * FROM trade_cooldown ORDER BY rowid DESC LIMIT 12"):
    print("  ", r)

print("\n=== trade_tp_ban (最近8) ===")
cols = [r[1] for r in c.execute("PRAGMA table_info(trade_tp_ban)")]
print("cols:", cols)
for r in c.execute("SELECT * FROM trade_tp_ban ORDER BY rowid DESC LIMIT 8"):
    print("  ", r)
