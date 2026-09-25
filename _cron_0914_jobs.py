#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查 cron jobs 中 NAS 备份 / 指定 id (只读)"""
import json
p = '/Users/zantao/.hermes/cron/jobs.json'
raw = json.load(open(p))
jobs = raw if isinstance(raw, list) else raw.get('jobs', raw)
if isinstance(jobs, dict):
    it = list(jobs.items())
else:
    it = [(x.get('id') or x.get('job_id'), x) for x in jobs]
print("total jobs:", len(it))
for k, v in it:
    s = json.dumps(v, ensure_ascii=False)
    nm = v.get('name') or v.get('title') or ''
    if ('64213b771537' in s) or ('nas' in s.lower()) or ('NAS' in s) or ('备份' in nm):
        print('---')
        print('id=', k, '| name=', nm, '| sched=', v.get('schedule'), '| enabled=', v.get('enabled'))
        for f in ('last_run', 'last_status', 'last_result', 'next_run', 'prompt'):
            val = v.get(f)
            if f == 'prompt' and val:
                val = str(val)[:120].replace('\n', ' ')
            print('   ', f, '=', val)
