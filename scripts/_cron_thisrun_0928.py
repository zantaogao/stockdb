import sqlite3, json
con = sqlite3.connect('file:/Users/zantao/.hermes/state.db?mode=ro', uri=True)
sid = 'cron_5128c85c245a_20260928_092433'
rows = con.execute("select role, content from messages where session_id=? order by id", (sid,)).fetchall()
print('n msgs:', len(rows))
# print any tool outputs containing meaningful exec_agent output
for role, c in rows:
    if role == 'tool' and c and '执行 Agent' in c:
        print('--- script stdout ---')
        print(c[:2000])
        break
else:
    # look for the first user message which contains injected script stdout
    for role, c in rows[:3]:
        if role == 'user' and c and '执行 Agent' in c:
            i = c.find('执行 Agent')
            print('--- injected stdout in user msg ---')
            print(c[i:i+800])
            break
# last assistant message
for role, c in reversed(rows):
    if role == 'assistant' and c and '[SILENT' not in c[:20]:
        print('--- assistant latest ---')
        print(c[:600])
        break
