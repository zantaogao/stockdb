import json
d = json.load(open('/Users/zantao/.hermes/cron/jobs.json'))
jobs = d if isinstance(d, list) else d.get('jobs', d)
for j in (jobs if isinstance(jobs, list) else jobs.values()):
    if '盘中决策 (9' in j.get('name',''):
        for k,v in j.items():
            s=str(v)
            print(k, '=', s[:300])
