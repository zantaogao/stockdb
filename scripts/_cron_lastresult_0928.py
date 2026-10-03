import json
d = json.load(open('/Users/zantao/.hermes/cron/jobs.json'))
jobs = d if isinstance(d, list) else d.get('jobs', d)
for j in (jobs if isinstance(jobs, list) else jobs.values()):
    if '盘中决策 (9' in j.get('name','') or '订单执行 (9' in j.get('name',''):
        print(j.get('name'), '| last_run:', j.get('last_run_at'), '| status:', j.get('last_status'))
        lr = j.get('last_result') or ''
        print('--- last stdout (tail 700 chars) ---')
        print(lr[-700:])
        print('======')
