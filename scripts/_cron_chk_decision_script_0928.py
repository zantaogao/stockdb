import subprocess, glob, os, time, json
d = json.load(open('/Users/zantao/.hermes/cron/jobs.json'))
jobs = d if isinstance(d, list) else d.get('jobs', d)
for j in (jobs if isinstance(jobs, list) else jobs.values()):
    if '盘中决策 (9' in j.get('name',''):
        print('script:', j.get('script'))
# tail of intraday decision output if it logs anywhere
for f in sorted(glob.glob('/Users/zantao/.hermes/stockdb/logs/*decision*') + glob.glob('/Users/zantao/.hermes/stockdb/logs/*intraday*'), key=os.path.getmtime)[-3:]:
    print(f, time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(f))))
