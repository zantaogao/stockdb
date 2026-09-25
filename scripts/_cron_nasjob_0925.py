import json, os, glob, subprocess, time
p = os.path.expanduser('~/.hermes/cron/jobs.json')
jobs = json.load(open(p))
js = jobs if isinstance(jobs, list) else jobs.get('jobs', list(jobs.values()) if isinstance(jobs, dict) else [])
for j in js:
    if isinstance(j, dict) and j.get('id') == '64213b771537':
        print(json.dumps(j, ensure_ascii=False, default=str)[:3000])
print('=== cron logs for NAS job ===')
for pat in ['~/.hermes/cron/logs/*64213b771537*', '~/.hermes/logs/*nas*', '~/.hermes/stockdb/logs/*nas*']:
    for f in glob.glob(os.path.expanduser(pat)):
        print(f, time.strftime('%F %T', time.localtime(os.path.getmtime(f))), os.path.getsize(f))
