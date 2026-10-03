import json, sqlite3
d = json.load(open('/Users/zantao/.hermes/cron/jobs.json'))
jobs = d if isinstance(d, list) else d.get('jobs', d)
rows = []
for j in (jobs if isinstance(jobs, list) else jobs.values()):
    sched = j.get('schedule', {})
    expr = sched.get('expr', '') if isinstance(sched, dict) else str(sched)
    rows.append((j.get('name', '?'), expr, j.get('enabled')))
# print only trading-morning relevant or all names briefly
for n, e, en in rows:
    print(f"{n} | {e} | {'on' if en else 'off'}")
