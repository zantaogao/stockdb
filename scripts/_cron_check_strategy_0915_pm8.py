#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找出策略账户日更 job 及其最近执行记录/输出"""
import json, os, sqlite3, glob

J = os.path.expanduser('~/.hermes/cron/jobs.json')
jobs = json.load(open(J))
if isinstance(jobs, dict):
    jobs = jobs.get('jobs', jobs)
for j in (jobs if isinstance(jobs, list) else jobs.values()):
    if not isinstance(j, dict):
        continue
    blob = json.dumps(j, ensure_ascii=False)
    if 'strategy_accounts_daily.sh' in blob and '监督任务' in blob:
        print("JOB:", j.get('id'), "|", j.get('name'), "|", j.get('schedule'), "|", j.get('command', '')[:120])
        jid = j.get('id')
        break
else:
    jid = None
    print("job not found by filter")

outdir = os.path.expanduser(f'~/.hermes/cron/output/{jid}') if jid else None
print("\nOUTPUT DIR:", outdir)
if outdir and os.path.isdir(outdir):
    files = sorted(glob.glob(outdir + '/*'), key=os.path.getmtime, reverse=True)[:6]
    for f in files:
        print(f"  {os.path.getmtime(f)} {f}")
    if files:
        print("\n--- newest log tail ---")
        print(open(files[0], errors='replace').read()[-3000:])

db = os.path.expanduser('~/.hermes/cron/executions.db')
if os.path.exists(db):
    c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    print("\nEXEC TABLES:", [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")])
    try:
        cols = [r[1] for r in c.execute("PRAGMA table_info(executions)")]
        q = f"SELECT * FROM executions WHERE job_id='{jid}' ORDER BY rowid DESC LIMIT 6"
        for r in c.execute(q):
            print("  ", dict(zip(cols, r)))
    except Exception as e:
        print("ERR", e)
