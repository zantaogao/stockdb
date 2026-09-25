#!/usr/bin/env python3
"""临时 cron 状态检查（_cron_* 惯例，留原地不清理）"""
import json

raw = json.load(open('/Users/zantao/.hermes/cron/jobs.json'))
jobs = raw.get('jobs', raw) if isinstance(raw, dict) else raw
if isinstance(jobs, dict):
    jobs = list(jobs.values())
for j in jobs:
    if not isinstance(j, dict):
        continue
    jid = str(j.get('id') or j.get('job_id') or '?')[:12]
    print(jid, '|', j.get('name', '?'), '| last_status=', j.get('last_status'),
          '| enabled=', j.get('enabled'), '| paused=', j.get('paused'))
