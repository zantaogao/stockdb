import sqlite3, glob, os
con = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
cur = con.cursor()
# last 15 trades overall to see dates/format
for r in cur.execute("SELECT trade_date,strategy,code,name,direction,price,quantity FROM trade_log ORDER BY id DESC LIMIT 15"):
    print(r)
print('---- distinct strategies:', [r[0] for r in cur.execute("SELECT DISTINCT strategy FROM trade_log")])
con.close()
# where are strategy NAVs stored?
print('sim json files:', glob.glob('/Users/zantao/.hermes/stockdb/sim_accounts/*.json')[:20])
