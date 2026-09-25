#!/usr/bin/env python3
from core import db

# tushare.db
conn_tushare = db.get_tushare_db()
n1 = conn_tushare.execute("SELECT COUNT(*) FROM stock_basic").fetchone()[0]
print(f"tushare.db stock_basic: {n1}只")

# state.db
conn_state = db._safe_connect('state.db')
n2 = conn_state.execute("SELECT COUNT(*) FROM stock_basic").fetchone()[0]
print(f"state.db stock_basic: {n2}只")

conn_tushare.close()
conn_state.close()
