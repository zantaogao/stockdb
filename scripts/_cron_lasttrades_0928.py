import sqlite3
con = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro', uri=True)
cols=[c[1] for c in con.execute('pragma table_info(trade_log)')]
print(cols)
for r in con.execute("select id,code,name,direction,quantity,price,trade_date,trade_time from trade_log order by id desc limit 5").fetchall():
    print(r)
