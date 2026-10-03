import json, os
p = os.path.expanduser('~/.hermes/cron/jobs.json')
jobs = json.load(open(p))
print('top keys:', list(jobs.keys()))
inner = jobs.get('jobs')
if isinstance(inner, dict):
    items = list(inner.values())
elif isinstance(inner, list):
    items = inner
else:
    items = []
for j in items:
    if not isinstance(j, dict):
        continue
    blob = json.dumps(j, ensure_ascii=False)
    if 'strategy_accounts' in blob or '策略账户日更' in blob:
        print('ID:', j.get('id'), '| name:', j.get('name'), '| sched:', j.get('schedule'), '| enabled:', j.get('enabled'))
        print('last_run:', j.get('last_run'), '| last_status:', j.get('last_status'))
        for k, v in j.items():
            if k in ('prompt',):
                print('prompt:', str(v)[:300])
            elif 'script' in k or 'command' in k or 'log' in k:
                print(k, '=', str(v)[:300])
        print('---')
