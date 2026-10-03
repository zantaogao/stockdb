import sqlite3
con = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro', uri=True)
con.row_factory = sqlite3.Row
cur = con.cursor()
print("--- trade_log today (20260929):")
for r in cur.execute("SELECT * FROM trade_log WHERE trade_date LIKE '2026-09-29%' OR trade_date LIKE '20260929%' ORDER BY id"):
    print(dict(r))
print("--- execution_logs last 5:")
for r in cur.execute("SELECT * FROM execution_logs ORDER BY rowid DESC LIMIT 5"):
    print(dict(r))
print("--- account_balance:")
for r in cur.execute("SELECT * FROM account_balance"):
    print(dict(r))
print("--- watchlist 603585/300982 recent:")
for r in cur.execute("SELECT * FROM watchlist WHERE ts_code LIKE '603585%' OR ts_code LIKE '300982%' ORDER BY created_at DESC LIMIT 6"):
    print(dict(r))
print("--- holdings 603585:")
for r in cur.execute("SELECT * FROM holdings WHERE code LIKE '603585%'"):
    print(dict(r))
