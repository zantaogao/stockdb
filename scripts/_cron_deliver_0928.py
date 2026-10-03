import json
d = json.load(open('/Users/zantao/.hermes/cron/jobs.json'))
jobs = d if isinstance(d, list) else d.get('jobs', d)
for j in (jobs if isinstance(jobs, list) else jobs.values()):
    if j.get('id','').startswith('5128c85c245a'):
        print('deliver:', j.get('deliver'))
