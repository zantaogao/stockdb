#!/usr/bin/env python3
"""_cron_ic_check.py — 查证 etf_ic/cmmr_ic_daily/fusion_ic_daily 缺失性质（2026-08-04 cron）"""
import sqlite3

conn = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')

def show(table, order_cols='rowid', limit=5):
    print(f"\n=== {table} ===")
    try:
        cur = conn.execute(f"SELECT * FROM {table} ORDER BY {order_cols} DESC LIMIT {limit}")
        cols = [d[0] for d in cur.description]
        print("列:", cols)
        for row in cur.fetchall():
            print(" ", row)
    except Exception as e:
        print(f"  查询失败: {e}")

# etf_ic
show('etf_ic')
# cmmr_ic_daily
show('cmmr_ic_daily')
# fusion_ic_daily
show('fusion_ic_daily')

# 检查 08-03 周一该算的行是否存在（signal_date=20260803 或 2026-08-03）
for tbl, datecol in [('etf_ic', None), ('cmmr_ic_daily', None), ('fusion_ic_daily', None)]:
    try:
        cur = conn.execute(f"SELECT * FROM {tbl} LIMIT 1")
        cols = [d[0] for d in cur.description]
        # 找可能的日期列
        date_cols = [c for c in cols if 'date' in c.lower()]
        print(f"\n{tbl} 日期列: {date_cols}")
        for dc in date_cols:
            try:
                rows = conn.execute(f"SELECT {dc}, count(*) FROM {tbl} GROUP BY 1 ORDER BY 1 DESC LIMIT 5").fetchall()
                print(f"  {dc} 最新5个值: {rows}")
            except Exception as e:
                print(f"  {dc} 查询失败: {e}")
    except Exception as e:
        print(f"\n{tbl} 表查询失败: {e}")

conn.close()
