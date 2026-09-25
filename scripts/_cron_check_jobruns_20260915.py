import sqlite3, os
c = sqlite3.connect(os.path.expanduser('~/.hermes/cron/executions.db'))
cols = [r[1] for r in c.execute("PRAGMA table_info(executions)")]
rows = c.execute("SELECT * FROM executions WHERE job_id='051af215dc32' ORDER BY rowid DESC LIMIT 12").fetchall()
for r in rows:
    d = dict(zip(cols, r))
    print(d['claimed_at'], d['status'], 'err=', d['error'], 'delivery=', d['delivery_outcome'])
c.close()
