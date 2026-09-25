import sqlite3

c = sqlite3.connect('/Users/zantao/.hermes/state.db')
rows = c.execute("""SELECT role, tool_name, length(content), substr(content,1,600)
                    FROM messages WHERE session_id='cron_099aee371ab5_20260901_225545'
                    ORDER BY id LIMIT 8""").fetchall()
for role, tn, ln, content in rows:
    print(f'### {role} tool={tn} len={ln}')
    print(content[:600])
    print()