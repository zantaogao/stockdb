import json, os, sqlite3, datetime
p = os.path.expanduser('~/.hermes/cron/jobs.json')
raw = json.load(open(p))
lst = raw if isinstance(raw, list) else raw.get('jobs', raw)
items = lst if isinstance(lst, list) else list(lst.values())
for j in items:
    blob = str(j.get('name','')) + ' ' + str(j.get('prompt',''))[:200]
    if '策略账户日更' in blob or 'strategy_accounts_daily' in blob:
        print("JOB:", j.get('id'), '|', j.get('name'), '|', j.get('schedule'), '| enabled=', j.get('enabled'),
              '| last_status=', j.get('last_status'), '| last_run=', j.get('last_run'))
edb = os.path.expanduser('~/.hermes/cron/executions.db')
if os.path.exists(edb):
    c = sqlite3.connect(edb)
    cols = [r[1] for r in c.execute("PRAGMA table_info(executions)")]
    print("exec cols:", cols)
    for r in c.execute("SELECT * FROM executions ORDER BY rowid DESC LIMIT 5"):
        print("  ", dict(zip(cols, r)))
    c.close()
