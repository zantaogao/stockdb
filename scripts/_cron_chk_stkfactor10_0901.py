import sqlite3

c = sqlite3.connect('/Users/zantao/.hermes/state.db')
rows = c.execute("""SELECT id, role, substr(content,1,300) FROM messages
    WHERE session_id='cron_099aee371ab5_20260901_225545' AND role='tool'
    ORDER BY id LIMIT 3""").fetchall()
for i, role, content in rows:
    print(i, repr(content[:200]))
    print()