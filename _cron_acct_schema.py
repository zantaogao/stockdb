#!/usr/bin/env python3
import sqlite3
sdb = sqlite3.connect("/Users/zantao/.hermes/stockdb/state.db")
cols = sdb.execute("PRAGMA table_info(account_balance)").fetchall()
print("account_balance columns:", [c[1] for c in cols])
rows = sdb.execute("SELECT * FROM account_balance ORDER BY rowid DESC LIMIT 3").fetchall()
for r in rows:
    print(r)
sdb.close()
