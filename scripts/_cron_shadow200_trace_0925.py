#!/usr/bin/env python3
# 0924夜 200只影子分的来历：查 executions.db 昨晚 shadow 任务运行记录 + cron output 落盘
import sqlite3, json
from pathlib import Path

# 1. executions.db 里昨晚 23:00~今晨 01:00 的任务运行（找 shadow/复权相关）
try:
    ex = sqlite3.connect('/Users/zantao/.hermes/cron/executions.db', timeout=10)
    rows = ex.execute("""
        SELECT job_id, substr(started_at,1,19), status, substr(coalesce(error,'')
        ,1,60) FROM executions
        WHERE started_at >= '2026-09-24 22:00' AND started_at <= '2026-09-25 01:30'
        ORDER BY started_at""").fetchall()
    jobs = {j['id']: j.get('name', '') for j in
            json.load(open('/Users/zantao/.hermes/cron/jobs.json'))['jobs']}
    for r in rows:
        print('EXEC', r[0][:12], jobs.get(r[0], '?'), r[1], r[2], r[3])
except Exception as e:
    print('executions.db 查询失败:', e)

# 2. cron/output 里 3f7866e772ec 的落盘（夜间巡逻-全链数据核验输出，昨晚跑过？）
for p in sorted(Path('/Users/zantao/.hermes/cron/output').glob('*')):
    if p.is_dir():
        sub = sorted(p.glob('*.md') + p.glob('*.txt') + p.glob('*.log') + p
        .glob('*'), key=lambda x: x.stat().st_mtime, reverse=True)[:1]
        for f in sub:
            if f.stat().st_mtime > 1758657600:  # 0924 20:00 之后
                print('OUT', p.name, f.name, __import__('datetime').datetime.fromtimestamp(f.stat().st_mtime))
