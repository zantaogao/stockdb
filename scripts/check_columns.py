#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('state.db')
cursor = conn.execute("PRAGMA table_info(signal_history)")
columns = [row[1] for row in cursor.fetchall()]
print(f"signal_history 表的所有列：")
for i, col in enumerate(columns):
    print(f"  {i+1}. {col}")
conn.close()
