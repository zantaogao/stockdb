#!/usr/bin/env python3
"""_cron_jobs.py — 查相关 cron 的调度/状态/prompt 摘要（2026-08-04）"""
import json, re

jobs = json.load(open('/Users/zantao/.hermes/cron/jobs.json'))
jobs = jobs if isinstance(jobs, list) else jobs.get('jobs', [])

ids = ['225e2591a8c4', 'd53fe84ebc8e', '2e6608b25eae', '273036bc5fc0', '20bd016556be', '051af215dc32', '0eeb7c55a480']
for j in jobs:
    jid = j.get('id', '')
    if jid in ids:
        name = j.get('name', '')
        sched = j.get('schedule') or j.get('cron') or ''
        enabled = j.get('enabled')
        last_status = j.get('last_status')
        last_run = j.get('last_run_at')
        prompt = j.get('prompt', '') or ''
        # 提取 prompt 中的脚本引用
        scripts = re.findall(r'([\w/]+\.py)', prompt)
        print(f"=== {jid} | {name}")
        print(f"  schedule: {sched} | enabled: {enabled} | last_status: {last_status} | last_run: {last_run}")
        print(f"  scripts: {scripts}")
        print()
