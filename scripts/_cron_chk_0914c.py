import sqlite3, os, datetime
base = os.path.expanduser('~/.hermes/stockdb')
c = sqlite3.connect(os.path.join(base, 'ledger.db'))
c.row_factory = sqlite3.Row
print('==== cooldown (sell_date>="20260901") ====')
for r in c.execute("SELECT * FROM trade_cooldown WHERE REPLACE(sell_date,'-','')>='20260901' ORDER BY sell_date DESC LIMIT 20"):
    print(dict(r))
print('==== tp_ban last 10 ====')
for r in c.execute("SELECT * FROM trade_tp_ban ORDER BY rowid DESC LIMIT 10"):
    print(dict(r))
print('==== ca_adjustments last 8 ====')
for r in c.execute("SELECT * FROM ca_adjustments ORDER BY rowid DESC LIMIT 8"):
    print(dict(r))
print('==== ca_run_log last 8 ====')
for r in c.execute("SELECT * FROM ca_run_log ORDER BY rowid DESC LIMIT 8"):
    print(dict(r))
print('==== trade_log strategy rows since 20260908 ====')
for r in c.execute("SELECT id,code,name,direction,price,quantity,trade_date,trade_time,strategy,notes FROM trade_log WHERE REPLACE(trade_date,'-','')>='20260908' ORDER BY REPLACE(trade_date,'-',''), id"):
    print(tuple(r))
