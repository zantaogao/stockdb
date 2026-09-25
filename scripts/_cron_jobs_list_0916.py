#!/usr/bin/env python3
"""列出所有 cron job 的 name/expr/script/状态（只读）"""
import json
p = '/Users/zantao/.hermes/cron/jobs.json'
d = json.load(open(p))
jobs = d['jobs'] if isinstance(d, dict) and 'jobs' in d else d
print('total jobs:', len(jobs))
for j in jobs:
    sch = j.get('schedule') or {}
    expr = sch.get('expr') or sch.get('display')
    print(f"{expr:<22} | {j.get('name','?'):<28} | script={j.get('script')} | enabled={j.get('enabled')} | last={j.get('last_run_at')} | {j.get('last_status')}")
