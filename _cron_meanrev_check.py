import json

data = json.load(open('/Users/zantao/.hermes/cron/jobs.json'))
jobs = data['jobs']
for j in jobs:
    if isinstance(j, dict) and j.get('id') == '11e324945c43':
        print('name:', j.get('name'))
        print('prompt:', j.get('prompt'))
        print('enabled:', j.get('enabled'))
        print('next_run_at:', j.get('next_run_at'))
