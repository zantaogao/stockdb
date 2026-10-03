import glob, os, time
pats = ['*defense*', '*decision*', '*exec*']
for p in pats:
    for f in glob.glob('/Users/zantao/.hermes/logs/'+p) + glob.glob('/Users/zantao/.hermes/stockdb/logs/'+p):
        print(time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(f))), f)
print('---')
# cron daemon logs?
for f in glob.glob('/Users/zantao/.hermes/cron/*.log') + glob.glob('/Users/zantao/.hermes/logs/*.log'):
    print(time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(f))), f)
