import sqlite3
con = sqlite3.connect("file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro", uri=True)
cur = con.cursor()
cols = [c[1] for c in cur.execute("PRAGMA table_info(strategy_positions)")]
print("strategy_positions cols:", cols)
print("center_dual positions:")
for r in cur.execute("SELECT code,name,shares,buy_date FROM strategy_positions WHERE account_id='center_dual' ORDER BY buy_date"):
    print("  ", r)
print("agent_auto positions:")
for r in cur.execute("SELECT code,name,shares,buy_date FROM strategy_positions WHERE account_id='agent_auto' ORDER BY buy_date"):
    print("  ", r)
con.close()
