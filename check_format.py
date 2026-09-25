#!/usr/bin/env python3
from core import db

# 检查已写入的格式
conn_state = db._safe_connect('state.db')
rows = conn_state.execute("SELECT stock_code FROM signal_history LIMIT 5").fetchall()
print("已写入的 stock_code:")
for r in rows:
    print(f"  {r[0]}")

# 检查 state.db 的 stock_basic 格式
rows2 = conn_state.execute("SELECT stock_code FROM stock_basic LIMIT 5").fetchall()
print("\nstate.db stock_basic 的 stock_code:")
for r in rows2:
    print(f"  {r[0]}")

conn_state.close()
