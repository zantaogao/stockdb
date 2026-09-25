import sqlite3, os
con = sqlite3.connect("file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro", uri=True)
cur = con.cursor()
tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print('ledger tables:', tabs)
print("2026-09-24 trades by account/dir:")
for r in cur.execute("SELECT strategy, direction, COUNT(*) FROM trade_log WHERE trade_date='2026-09-24' GROUP BY strategy, direction"):
    print("  ", r)
print("2026-09-24 detail (latest 15):")
cols = [c[1] for c in cur.execute("PRAGMA table_info(trade_log)")]
print("  cols:", cols)
for r in cur.execute("SELECT * FROM trade_log WHERE trade_date='2026-09-24' ORDER BY rowid DESC LIMIT 15"):
    print("  ", r)
con.close()
