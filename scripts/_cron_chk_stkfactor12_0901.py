import json

jobs = json.load(open('/Users/zantao/.hermes/cron/jobs.json'))
jl = jobs if isinstance(jobs, list) else jobs.get('jobs', [])
for j in jl:
    if j.get('id') in ('4cf29c666951', 'ee38c4107fbe'):
        print(j['id'], j.get('name'), '| script:', j.get('script'), '| enabled:', j.get('enabled'),
              '| last_run:', j.get('last_run_at'), '| status:', j.get('last_status'))

# Did the 22:00 run get killed? Check last messages of the failed cron session
import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/state.db')
rows = c.execute("""SELECT id, role, tool_name, substr(content,1,120) FROM messages
    WHERE session_id='cron_099aee371ab5_20260901_225545' ORDER BY id DESC LIMIT 5""").fetchall()
for r in rows:
    print('TAIL:', r)