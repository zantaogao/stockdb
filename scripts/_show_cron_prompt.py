import json, sys
j = json.load(open('/Users/zantao/.hermes/cron/jobs.json'))['jobs']
jobs = j if isinstance(j, list) else list(j.values())
want = sys.argv[1] if len(sys.argv) > 1 else None
for x in jobs:
    pid = x.get('job_id') or x.get('id') or ''
    if pid == want or (not want and '综合报告' in (x.get('name') or '')):
        print(x.get('name'), '\n====PROMPT====')
        print(x.get('prompt', ''))
        break
else:
    for x in jobs:
        print(x.get('job_id') or x.get('id'), x.get('name'))