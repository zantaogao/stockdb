import json, subprocess, pathlib, time
# Where does orders/pending.json get written? Check risk_agent + intraday_decision last runs / cron last-run statuses
d = json.load(open('/Users/zantao/.hermes/cron/jobs.json'))
jobs = d if isinstance(d, list) else d.get('jobs', d)
for j in (jobs if isinstance(jobs, list) else jobs.values()):
    n = j.get('name','?')
    if any(k in n for k in ('盘中决策','订单执行','夜间巡逻','盘前报告')):
        st = j.get('last_status'), j.get('last_run_at'), j.get('last_result')
        print(n, '|', st[0], '|', st[1])
# recent executed orders files
import glob, os
for f in sorted(glob.glob('/Users/zantao/.hermes/stockdb/orders/*'), key=os.path.getmtime)[-5:]:
    print(f, time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(f))))
