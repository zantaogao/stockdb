import json, os, datetime
p = os.path.expanduser('~/.hermes/cron/jobs.json')
jobs = json.load(open(p))
js = jobs if isinstance(jobs, list) else jobs.get('jobs', list(jobs.values()) if isinstance(jobs, dict) else [])
for j in js:
    if not isinstance(j, dict):
        continue
    n = str(j.get('name', ''))
    if '备份' in n or 'NAS' in n.upper() or 'backup' in n.lower():
        print(json.dumps({k: j.get(k) for k in ('id', 'name', 'schedule', 'last_status', 'last_run', 'next_run', 'enabled') if k in j}, ensure_ascii=False, default=str))
print('---jobs with check_and_alert / health---')
for j in js:
    if not isinstance(j, dict):
        continue
    n = str(j.get('name', ''))
    cmd = str(j.get('command', '')) + str(j.get('prompt', ''))
    if 'check_and_alert' in cmd or '链路健康' in n or '健康检查' in n:
        print(json.dumps({k: j.get(k) for k in ('id', 'name', 'schedule', 'last_status', 'last_run', 'next_run') if k in j}, ensure_ascii=False, default=str))
