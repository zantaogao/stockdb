import sqlite3
con = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
print("--- last 25 trade_log rows ---")
for r in con.execute("select trade_date,trade_time,strategy,code,name,direction,price,quantity from trade_log order by rowid desc limit 25").fetchall():
    print(r)