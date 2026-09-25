import sqlite3, os
p = os.path.expanduser('~/.hermes/cron/executions.db')
print([r[0] for r in sqlite3.connect(p).execute("SELECT name FROM sqlite_master WHERE type='table'")])
con = sqlite3.connect(p); con.row_factory = sqlite3.Row
cur = con.cursor()
print([r[1] for r in cur.execute("PRAGMA table_info(executions)")])
for r in cur.execute("""SELECT * FROM executions WHERE job_id IN ('051af215dc32','897902eea54a','603c3274e5ff','30bee53b6e14')
                        ORDER BY rowid DESC LIMIT 15"""):
    print(dict(r))
