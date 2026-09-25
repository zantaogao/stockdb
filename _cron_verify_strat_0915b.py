import sqlite3, os, json, glob
LED = os.path.expanduser('~/.hermes/stockdb/ledger.db')
con = sqlite3.connect(LED); con.row_factory = sqlite3.Row; cur = con.cursor()

print("=== strategy_accounts_meta ===")
print([r[1] for r in cur.execute("PRAGMA table_info(strategy_accounts_meta)")])
for r in cur.execute("SELECT * FROM strategy_accounts_meta"):
    d = dict(r)
    print({k: d[k] for k in list(d)[:8]})

print("\n=== 300311 in strategy_positions ===")
rows = list(cur.execute("SELECT * FROM strategy_positions WHERE code LIKE '%300311%'"))
print(rows if rows else "NONE (已清仓)")

print("\n=== 300311 全表流水 (cmmr) ===")
for r in cur.execute("SELECT * FROM trade_log WHERE code LIKE '%300311%' ORDER BY id DESC LIMIT 8"):
    print(dict(r))

print("\n=== 各账户持仓数 + 现金 ===")
for r in cur.execute("SELECT account_id, COUNT(*) n, SUM(shares*avg_cost) cost FROM strategy_positions GROUP BY account_id"):
    print(dict(r))
print("--- meta 现金 ---")
for r in cur.execute("SELECT * FROM strategy_accounts_meta"):
    d=dict(r); print(d)
