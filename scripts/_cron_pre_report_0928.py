import json
con_rep = None
import json
d = json.load(open('/Users/zantao/.hermes/cron/jobs.json'))
jobs = d if isinstance(d, list) else d.get('jobs', d)
for j in (jobs if isinstance(jobs, list) else jobs.values()):
    if j.get('id','').startswith('6bcc281a869f'):
        lr = j.get('last_result') or ''
        print('last_run:', j.get('last_run_at'), 'status:', j.get('last_status'))
        print('deliver:', j.get('deliver'))
        print('result tail 1500:')
        print(lr[-1500:])
