import sqlite3, os
con = sqlite3.connect("file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro", uri=True)
cur = con.cursor()
# actual buys per account today (first leg)
print("today BUY by account:")
for r in cur.execute("SELECT strategy, COUNT(*) FROM trade_log WHERE trade_date='2026-09-24' AND direction='BUY' GROUP BY strategy"):
    print("  ", r)
print("today SELL by account:")
for r in cur.execute("SELECT strategy, COUNT(*) FROM trade_log WHERE trade_date='2026-09-24' AND direction='SELL' GROUP BY strategy"):
    print("  ", r)
# account_auto holdings today
print("\nagent_auto positions (sim_accounts):")
import json
d = os.path.expanduser("~/.hermes/stockdb/scripts/sim_accounts")
if not os.path.isdir(d):
    import glob
    cands = glob.glob(os.path.expanduser("~/.hermes/stockdb/**/sim_accounts"), recursive=True)
    d = cands[0] if cands else None
if d:
    j = json.load(open(os.path.join(d, "agent_auto.json")))
    pos = j.get("positions") or j.get("holdings") or {}
    print("  hold codes:", list(pos.keys()) if isinstance(pos, dict) else pos)
con.close()
