#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定位 job 输出目录 + 本 tick 执行记录（修正 executions.db 只读打开）"""
import json, os, sqlite3, glob, time

jobs = json.load(open(os.path.expanduser('~/.hermes/cron/jobs.json')))
if isinstance(jobs, dict):
    jobs = jobs.get('jobs', jobs)
jid = None
for j in (jobs if isinstance(jobs, list) else jobs.values()):
    if isinstance(j, dict) and 'strategy_accounts_daily.sh' in json.dumps(j, ensure_ascii=False) and '监督任务' in json.dumps(j, ensure_ascii=False):
        jid = j.get('id'); print("JOB:", jid, "|", j.get('name'), "|", j.get('schedule'))
        break

outdir = os.path.expanduser(f'~/.hermes/cron/output/{jid}')
print("OUTDIR:", outdir, "exists:", os.path.isdir(outdir))
files = sorted(glob.glob(outdir + '/*'), key=os.path.getmtime, reverse=True)[:8] if os.path.isdir(outdir) else []
for f in files:
    print("  ", time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(f))), os.path.basename(f), os.path.getsize(f))

for p in ('executions.db', 'cron.db', 'jobs.db'):
    fp = os.path.expanduser('~/.hermes/cron/' + p)
    print(f"\n=== {p} size={os.path.getsize(fp) if os.path.exists(fp) else 'MISSING'}")
    if not os.path.exists(fp) or os.path.getsize(fp) == 0:
        continue
    try:
        c = sqlite3.connect(fp)
        tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        print("  tables:", tabs)
        for t in tabs:
            cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
            if 'job_id' in cols:
                try:
                    for r in c.execute(f"SELECT * FROM {t} WHERE job_id=? ORDER BY rowid DESC LIMIT 4", (jid,)):
                        print("   ", dict(zip(cols, r)))
                except Exception as e:
                    print("   ERR", e)
    except Exception as e:
        print("  OPEN ERR", e)
