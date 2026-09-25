import sqlite3, json, os, glob, datetime

LED = os.path.expanduser('~/.hermes/stockdb/ledger.db')
con = sqlite3.connect(LED)
con.row_factory = sqlite3.Row
cur = con.cursor()

print("=== tables ===")
print([r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")])

print("\n=== trade_log schema ===")
print([r[1] for r in cur.execute("PRAGMA table_info(trade_log)")])

print("\n=== recent trade_log (last 12) ===")
for r in cur.execute("SELECT * FROM trade_log ORDER BY rowid DESC LIMIT 12"):
    d = dict(r)
    print(d)

print("\n=== trade_log on 20260915 ===")
for r in cur.execute("SELECT * FROM trade_log WHERE REPLACE(trade_date,'-','')='20260915' ORDER BY rowid"):
    print(dict(r))

print("\n=== strategy_positions cols ===")
print([r[1] for r in cur.execute("PRAGMA table_info(strategy_positions)")])
print("\n=== 300311 positions across accounts ===")
for r in cur.execute("SELECT * FROM strategy_positions WHERE stock_code LIKE '%300311%'"):
    print(dict(r))
