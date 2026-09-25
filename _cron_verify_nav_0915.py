import sqlite3, os
LED = os.path.expanduser('~/.hermes/stockdb/ledger.db')
con = sqlite3.connect(LED); con.row_factory = sqlite3.Row; cur = con.cursor()
print("=== strategy_accounts_legacy schema ===")
print([r[1] for r in cur.execute("PRAGMA table_info(strategy_accounts_legacy)")])
print("\n=== 20260915 NAV rows ===")
cols = [r[1] for r in cur.execute("PRAGMA table_info(strategy_accounts_legacy)")]
dcol = 'date' if 'date' in cols else cols[1]
for r in cur.execute(f"SELECT * FROM strategy_accounts_legacy WHERE REPLACE(date,'-','')='20260915' ORDER BY account_id"):
    d = dict(r)
    print({k: d.get(k) for k in ('account_id','date','nav','total_value','cash','daily_return','cum_return') if k in d})
print("\n=== 各账户最近2条 ===")
for r in cur.execute(f"""SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY REPLACE(date,'-','') DESC) rn
    FROM strategy_accounts_legacy) WHERE rn<=2 ORDER BY account_id, rn"""):
    d=dict(r); print({k: d.get(k) for k in ('account_id','date','nav','daily_return') if k in d})
print("\n=== NAV history keys (json?) ===")
print([c for c in cols][:20])
