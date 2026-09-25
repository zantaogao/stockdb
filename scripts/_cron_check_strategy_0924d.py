import sqlite3, os, json
con = sqlite3.connect("file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro", uri=True)
cur = con.cursor()
# center_dual sells today beyond 1?
for r in cur.execute("SELECT id,code,name,direction,price,trade_time,notes FROM trade_log WHERE trade_date='2026-09-24' AND strategy='center_dual' ORDER BY rowid"):
    print(r)
print("---agent_auto full today---")
for r in cur.execute("SELECT id,code,name,direction,price,trade_time FROM trade_log WHERE trade_date='2026-09-24' AND strategy='agent_auto' ORDER BY rowid"):
    print(r)
# check ca_run_log / defense_state last entries
print("---ca_run_log last 3---")
for r in cur.execute("SELECT * FROM ca_run_log ORDER BY rowid DESC LIMIT 3"):
    print(r)
con.close()
