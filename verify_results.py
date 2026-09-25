#!/usr/bin/env python3
from core import db

conn_state = db._safe_connect('state.db', read_only=True)

# 已写入数
written = conn_state.execute("SELECT COUNT(*) FROM signal_history WHERE date='2026-07-22'").fetchone()[0]
print(f"signal_history: {written}条")

# 缺失的股票总数
missing_count = conn_state.execute("""
    SELECT COUNT(*) FROM stock_basic 
    WHERE stock_code NOT IN (
        SELECT stock_code FROM signal_history WHERE date='2026-07-22'
    )
""").fetchone()[0]

print(f"缺失的股票总数：{missing_count}只")

# 显示缺失的股票代码
missing = conn_state.execute("""
    SELECT stock_code FROM stock_basic 
    WHERE stock_code NOT IN (
        SELECT stock_code FROM signal_history WHERE date='2026-07-22'
    )
    LIMIT 35
""").fetchall()

print(f"\n缺失的股票代码:")
for code, in missing:
    print(f"  {code}")

conn_state.close()
