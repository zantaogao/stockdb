import json, glob, os, re

def load_jobs(p):
    jobs = json.load(open(p))
    return jobs if isinstance(jobs, list) else jobs.get('jobs', jobs)

print("== jobs.json.bak* 里 growth_expert_retrain 出现情况（present/enabled）==")
rows = []
for f in sorted(glob.glob(os.path.expanduser('~/.hermes/cron/jobs.json.bak*'))):
    try:
        jl = load_jobs(f)
    except Exception as e:
        print(f, 'ERR', e); continue
    m = [j for j in jl if 'growth_expert_retrain' in json.dumps(j)]
    en = sum(1 for j in m if j.get('enabled'))
    mt = __import__('datetime').datetime.fromtimestamp(os.path.getmtime(f)).strftime('%m-%d %H:%M')
    rows.append((mt, os.path.basename(f), len(m), en))
for r in sorted(rows):
    print(*r)

jl = load_jobs(os.path.expanduser('~/.hermes/cron/jobs.json'))
m = [j for j in jl if 'growth_expert_retrain' in json.dumps(j)]
print("\n== 当前 jobs.json ==")
for j in m:
    print(j.get('id'), j.get('name'), 'enabled=', j.get('enabled'), 'cron=', j.get('schedule') or j.get('cron'))

# ACK 文件位置
import subprocess
out = subprocess.run(['/usr/bin/grep','-n','ACK_FILE','/Users/zantao/.hermes/scripts/cron_job_audit.py'],capture_output=True,text=True).stdout
print("\n== ACK_FILE 定义 ==\n", out)
