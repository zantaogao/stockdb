#!/usr/bin/env python3
import duckdb, os, sqlite3
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('file:ledger.db?mode=ro', uri=True)
rows = c.execute("SELECT code,name,status,buy_date,avg_cost,shares,latest_price,pnl,pnl_pct,target_price,stop_loss FROM holdings").fetchall()
print(len(rows), 'rows')
for r in rows: print(r)
t = duckdb.connect('tushare.db', read_only=True)
print('max date:', t.execute("SELECT MAX(trade_date) FROM daily").fetchone())
