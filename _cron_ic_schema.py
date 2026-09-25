#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_cron_ic_schema.py — 查 IC 相关表结构 (诊断用)"""
import sqlite3
conn = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
for t in ['factor_ic_roll', 'factor_group_ic_daily', 'factor_ic_daily', 'etf_ic', 'ic_daily']:
    try:
        cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
        print(f"\n{t}: {[(c[1], c[2]) for c in cols]}")
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  行数={n}")
        if n:
            sample = conn.execute(f"SELECT * FROM {t} ORDER BY rowid DESC LIMIT 1").fetchone()
            print(f"  最新行={sample}")
    except Exception as e:
        print(f"\n{t}: 查询失败 {e}")
conn.close()
