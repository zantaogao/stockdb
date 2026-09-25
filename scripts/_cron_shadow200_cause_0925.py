#!/usr/bin/env python3
# 200/4931 根因定案：shadow 任务昨晚运行状态 + limit 默认值 + ca_calendar 写入窗口
import json, sqlite3
jobs = json.load(open('/Users/zantao/.hermes/cron/jobs.json'))['jobs']
for j in jobs:
    if j['id'][:12] == '3f7866e772ec':
        print('shadow-fuquan 任务: last_run:', j.get('last_run_at'), '| status:', j.get('last_status'), '| last_error:', str(j.get('last_error'))[:200])

sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db', timeout=10)
print('ca_calendar 中 0924 除权事件:', sig.execute("SELECT COUNT(*) FROM ca_calendar WHERE ex_date='20260924'").fetchone())

src = open('/Users/zantao/.hermes/stockdb/scripts/shadow_fuquan_score.py').read()
for ln in src.splitlines():
    s = ln.strip()
    if 'add_argument' in s and ('limit' in s or 'date' in s) or s.startswith('ap.add'):
        print('ARG:', s[:110])
