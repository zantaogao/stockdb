#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('state.db')
row = conn.execute("SELECT COUNT(*) FROM signal_history WHERE REPLACE(date, '-', '') = '20260728'").fetchone()
print(f"signal_history 记录数：{row[0]}")
row2 = conn.execute("SELECT stock_code, cmmr_score, fusion_score FROM signal_history WHERE REPLACE(date, '-', '') = '20260728' LIMIT 3").fetchall()
print(f"示例数据：{row2}")
conn.close()
