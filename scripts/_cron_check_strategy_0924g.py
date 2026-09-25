import json, sqlite3, glob, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
s = sqlite3.connect('ledger.db')
db = {a: json.loads(c or '{}').get('last_rebalance_date') for a, c in s.execute("SELECT account_id, config_json FROM strategy_accounts_meta")}
print("DB accounts:", sorted(db))
drift = 0
for f in sorted(glob.glob('sim_accounts/*.json')):
    j = json.load(open(f))
    a = j.get('account_id')
    if a in db:
        d = j.get('last_rebalance_date')
        if d != db[a]:
            drift += 1
            print(f"DRIFT {a} json={d} db={db[a]}")
print("drift_count =", drift)
for f in sorted(glob.glob('sim_accounts/*.json')):
    j = json.load(open(f))
    navs = j.get('nav_history') or j.get('nav') or []
    last = navs[-1] if isinstance(navs, list) and navs else None
    print(os.path.basename(f), '->', last if not isinstance(last, dict) else {k: last[k] for k in list(last)[:3]})
