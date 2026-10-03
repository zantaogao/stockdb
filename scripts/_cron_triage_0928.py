"""0928 20:30 健康检查三条异常的核查：
1) signal_history 停更日期 2) watchlist 停更日期 3) tushare.db 备份面
4) jobs.json 0924模板 vs 现版 diff（找被删/停用的评分 cron）
5) executions.db 里 signal_agent 相关 job 近几天运行记录
"""
import json, sqlite3, datetime
from pathlib import Path

HB = Path.home() / '.hermes'

def load(f):
    d = json.load(open(f))
    return d if isinstance(d, list) else d.get('jobs', d)

old = load(HB/'cron/jobs.json.bak_0924_tpl')
new = load(HB/'cron/jobs.json')
oldm = {(j.get('id') or '')[:12]: j for j in old}
newm = {(j.get('id') or '')[:12]: j for j in new}
print('== jobs diff (0924模板 vs 现版) ==')
for k, j in oldm.items():
    if k not in newm:
        print('REMOVED:', k, j.get('name'), '|', j.get('script') or '(agent)', '|', j.get('state'))
for k, j in newm.items():
    if k not in oldm:
        print('ADDED:  ', k, j.get('name'), '|', j.get('script') or '(agent)', '|', j.get('state'))
for k in oldm:
    if k in newm:
        so, sn = oldm[k].get('state'), newm[k].get('state')
        if so != sn:
            print('STATE:  ', k, newm[k].get('name'), so, '->', sn)

print()
print('== signal_history / watchlist 最近5日行数 ==')
sig = sqlite3.connect(HB/'stockdb/signals.db', timeout=10)
rows = sig.execute("SELECT date, count(*) FROM signal_history GROUP BY date ORDER BY date DESC LIMIT 6").fetchall()
print('signal_history:', rows)
sig.close()
led = sqlite3.connect(HB/'stockdb/ledger.db', timeout=10)
rows = led.execute("SELECT scan_date, count(*), sum(status='pending') FROM watchlist GROUP BY scan_date ORDER BY scan_date DESC LIMIT 6").fetchall()
print('watchlist:', rows)
# watchlist表最后被写的痕迹: 用 max rowid
print('watchlist max rowid:', led.execute("SELECT max(rowid) FROM watchlist").fetchone())
led.close()

print()
print('== executions.db: 近3天所有 job 状态汇总 ==')
ex = sqlite3.connect(HB/'cron/executions.db', timeout=10)
rows = ex.execute("""
SELECT j.job_id, e.status, count(*), max(e.started_at)
FROM executions e JOIN (SELECT id AS job_id, id FROM executions) j ON 1=1
WHERE 0""").fetchall()
# simpler: recent executions with job name from jobs.json
jobs_now = {(j.get('id') or ''): (j.get('name') or '', j.get('script') or '') for j in new}
rows = ex.execute("""
SELECT job_id, status, started_at, finished_at, substr(coalesce(error,''),1,80)
FROM executions WHERE started_at >= '2026-09-28' ORDER BY started_at
""").fetchall()
seen = {}
for job_id, st, sa, fa, err in rows:
    name, script = jobs_now.get(job_id, (job_id[:12], '?'))
    key = (name, script, st)
    seen.setdefault(key, [0, ''])[0] += 1
    seen[key][1] = max(seen[key][1], str(sa))
for (name, script, st), (cnt, last) in sorted(seen.items(), key=lambda x: x[1][1], reverse=True):
    print(f"{cnt:3d}x {st:12s} last={last[:19]} {name} [{script}]")
print()
print('== watchlist 原始 scan_date 值分布 ==')
led = sqlite3.connect(HB/'stockdb/ledger.db', timeout=10)
print(led.execute("SELECT scan_date, count(*) FROM watchlist GROUP BY scan_date ORDER BY max(rowid) DESC LIMIT 10").fetchall())
print('holdings表最后写入痕迹 account_balance:')
print(led.execute("SELECT * FROM account_balance").fetchall()[:3])
led.close()
ex.close()
