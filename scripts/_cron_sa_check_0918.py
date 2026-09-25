import sqlite3, os
db = os.path.expanduser("~/.hermes/stockdb/ledger.db")
c = sqlite3.connect(db)
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
sa = [t for t in tabs if 'strateg' in t]
print("tables:", sa)
for t in sa:
    cols = [r[1] for r in c.execute(f"PRAGMA table_info('{t}')")]
    print(t, cols)
# account status/config
for t in sa:
    if 'account' in t or 'config' in t or t == 'strategy_accounts':
        for row in c.execute(f"SELECT * FROM {t}"):
            print(row)
# trades today for strategy accounts
try:
    rows = c.execute("SELECT * FROM trade_log WHERE date LIKE '2026-09-18%' OR date LIKE '20260918%'").fetchall()
    cols = [r[1] for r in c.execute("PRAGMA table_info('trade_log')")]
    print("trade_log 0918 count:", len(rows))
    for r in rows[:30]: print(r)
except Exception as e:
    print("trade_log err", e)
