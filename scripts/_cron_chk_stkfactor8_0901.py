import sqlite3

# Check the previous cron session for this job (yesterday's run) for how it reported
c = sqlite3.connect('/Users/zantao/.hermes/state.db')
rows = c.execute("""SELECT role, substr(content,1,2000) FROM messages
    WHERE session_id='cron_099aee371ab5_20260831_220928' AND role='assistant'
    ORDER BY id DESC LIMIT 2""").fetchall()
for role, content in rows:
    print('###', role)
    print(content)
    print()