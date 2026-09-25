import sqlite3, json, glob, os, time

db = sqlite3.connect('/Users/zantao/.hermes/cron/jobs.db') if os.path.exists('/Users/zantao/.hermes/cron/jobs.db') else None
# find where cron run history lives
import subprocess
for f in glob.glob('/Users/zantao/.hermes/cron/*.db') + glob.glob('/Users/zantao/.hermes/state/*.db'):
    print('DB file:', f)

# also check the 22:55 cron agent session transcript for what the injected script output was
log = '/Users/zantao/.hermes/logs/agent.log'
found = []
with open(log, encoding='utf-8', errors='replace') as fh:
    for line in fh:
        if 'cron_099aee371ab5_20260901_225545' in line and ('position 42' in line or 'Script execution failed' in line or 'codec' in line):
            found.append(line[:300])
print('matches in agent.log:', len(found))
for x in found[:5]:
    print(x)