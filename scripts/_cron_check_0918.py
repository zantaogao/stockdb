import sqlite3
db = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro', uri=True)
rows = db.execute("""SELECT trade_date,strategy,code,name,direction,price,quantity,notes FROM trade_log
    WHERE trade_date>='2026-09-17' ORDER BY trade_date DESC, id DESC LIMIT 60""").fetchall()
print("trades since 09-17:", len(rows))
for r in rows: print(r)
print("---strategy meta---")
print([c[1] for c in db.execute("PRAGMA table_info(strategy_accounts_meta)")])
for r in db.execute("SELECT * FROM strategy_accounts_meta").fetchall(): print(r)
