import sqlite3
con = sqlite3.connect("file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro", uri=True)
cur = con.cursor()
cols = [c[1] for c in cur.execute("PRAGMA table_info(holdings)")]
print("holdings cols:", cols)
codes = [r[0] for r in cur.execute("SELECT code FROM holdings WHERE strategy='agent_auto'")]
print("  codes:", codes)
bought = {r[0] for r in cur.execute("SELECT DISTINCT code FROM trade_log WHERE strategy='agent_auto' AND direction='BUY' AND trade_date<='2026-09-23'")}
sold = {r[0] for r in cur.execute("SELECT DISTINCT code FROM trade_log WHERE strategy='agent_auto' AND direction='SELL' AND trade_date<='2026-09-23'")}
# codes with no prior BUY at all
never = [c for c in codes if c not in bought]
print("  holdings with NO prior BUY record:", never)
con.close()
