import json, sqlite3, os, time
from pathlib import Path
p = Path('/Users/zantao/.hermes/stockdb/orders/pending.json')
print('pending exists:', p.exists())
if p.exists():
    print(json.load(open(p))['timestamp'])
con = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro', uri=True)
print('exec logs today:', con.execute("select exec_id,status from execution_logs where exec_id like '2026-09-28%'").fetchall())
print('trade_log today:', con.execute("select id,code,direction,price,quantity from trade_log where trade_date='2026-09-28'").fetchall())
print('holdings status:', con.execute("select code,status from holdings where code in ('301590','301110')").fetchall())
