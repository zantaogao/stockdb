import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
cols = [d[1] for d in c.execute("PRAGMA table_info(trade_log)")]
print("trade_log cols:", cols)
rows = c.execute("""SELECT * FROM trade_log WHERE trade_date LIKE '%2026-09-18%' OR trade_date LIKE '%20260918%'""").fetchall()
print("today total rows:", len(rows))
for r in rows:
    print(r)
print("== strategy_accounts_meta ==")
mcols=[d[1] for d in c.execute("PRAGMA table_info(strategy_accounts_meta)")]
print(mcols)
for r in c.execute("SELECT * FROM strategy_accounts_meta").fetchall():
    print(r)
