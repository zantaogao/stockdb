"""查询 state.db 表结构"""
import sqlite3

conn = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
cur = conn.cursor()

tables = ['ic_daily', 'factor_ic_roll', 'factor_group_ic_daily', 'fusion_3f_ic']
for t in tables:
    try:
        cols = cur.execute(f"PRAGMA table_info({t})").fetchall()
        print(f"\n[{t}]")
        for c in cols:
            print(f"  {c[1]} ({c[2]})")
    except Exception as e:
        print(f"\n[{t}] 不存在: {e}")

conn.close()
