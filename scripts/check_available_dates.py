#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('state.db')
rows = conn.execute("SELECT DISTINCT date FROM signal_history ORDER BY date DESC LIMIT 10").fetchall()
print("signal_history 中的日期:")
for row in rows:
    print(f"  {row[0]}")
conn.close()
