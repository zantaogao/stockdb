import sqlite3, json, glob, os
con = sqlite3.connect("/Users/zantao/.hermes/stockdb/ledger.db")
cur = con.cursor()
rows = cur.execute("SELECT account_id, date, nav, cash, n_pos, daily_ret FROM strategy_accounts WHERE date>='20260923' ORDER BY account_id, date").fetchall()
for r in rows: print(r)
con.close()
