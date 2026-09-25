import sqlite3, json

c = sqlite3.connect('/Users/zantao/.hermes/cron/executions.db')
cols = [r[1] for r in c.execute("PRAGMA table_info(executions)")]
print('cols:', cols)
rows = c.execute("SELECT * FROM executions ORDER BY rowid DESC LIMIT 3").fetchall()
for r in rows:
    d = dict(zip(cols, r))
    s = json.dumps({k: (str(v)[:400]) for k, v in d.items()}, ensure_ascii=False)
    print(s)
    print('---')