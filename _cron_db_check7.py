#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查 tdx_intraday_feat 停更原因 + cmmr_ic_daily 真实列名"""
import sqlite3, os
BASE = os.path.expanduser('~/.hermes/stockdb')
SD = os.path.join(BASE, 'state.db')
s = sqlite3.connect(SD)

print("--- tdx_intraday_feat ---")
cols = [r[1] for r in s.execute("PRAGMA table_info(tdx_intraday_feat)").fetchall()]
print("列:", cols)
rows = s.execute("SELECT date, COUNT(*) c FROM tdx_intraday_feat GROUP BY 1 ORDER BY 1 DESC LIMIT 8").fetchall()
print("最近 8 天:", " ".join(f"{r[0]}:{r[1]}" for r in rows))
# 看 date 列格式
rows = s.execute("SELECT date FROM tdx_intraday_feat ORDER BY rowid DESC LIMIT 5").fetchall()
print("最新 5 行 date:", [r[0] for r in rows])

print("\n--- cmmr_ic_daily / fusion_ic_daily ---")
for tbl in ['cmmr_ic_daily', 'fusion_ic_daily']:
    cols = [r[1] for r in s.execute(f"PRAGMA table_info({tbl})").fetchall()]
    print(f"{tbl} 列: {cols}")
    try:
        rows = s.execute(f"SELECT * FROM {tbl} ORDER BY rowid DESC LIMIT 3").fetchall()
        for r in rows:
            print("  ", r)
    except Exception as e:
        print("  ERROR:", e)

print("\n--- ic_daily 最近 3 行 ---")
cols = [r[1] for r in s.execute("PRAGMA table_info(ic_daily)").fetchall()]
print("列:", cols)
for r in s.execute("SELECT * FROM ic_daily ORDER BY signal_date DESC LIMIT 3").fetchall():
    print("  ", r)
s.close()
