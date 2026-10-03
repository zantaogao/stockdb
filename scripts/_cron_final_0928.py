from pathlib import Path
import glob, os, time, json
p = Path('/Users/zantao/.hermes/stockdb/orders/pending.json')
print('pending.json at check time:', p.exists())
d = json.load(open('/Users/zantao/.hermes/cron/jobs.json'))
jobs = d if isinstance(d, list) else d.get('jobs', d)
for j in (jobs if isinstance(jobs, list) else jobs.values()):
    n = j.get('name','')
    if '订单执行' in n or '盘中决策' in n:
        print(n, '| next_run:', j.get('next_run_at'), '| last:', j.get('last_run_at'), j.get('last_status'))
