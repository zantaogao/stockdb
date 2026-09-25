import sqlite3, json, glob, os, time

c = sqlite3.connect('/Users/zantao/.hermes/cron/jobs.db') if False else None
# cron job definition: fields we care about
jobs = json.load(open('/Users/zantao/.hermes/cron/jobs.json'))
jl = jobs if isinstance(jobs, list) else jobs.get('jobs', [])
for j in jl:
    if j.get('id') == '099aee371ab5':
        print(json.dumps(j, ensure_ascii=False, indent=1))

# recent output files in cron output dir, sorted by mtime (any job)
allf = glob.glob('/Users/zantao/.hermes/cron/output/*/*.md')
allf.sort(key=os.path.getmtime, reverse=True)
print('\nrecent cron outputs:')
for f in allf[:8]:
    print(time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(f))), f.split('output/')[1])