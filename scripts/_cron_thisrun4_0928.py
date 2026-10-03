import sqlite3
con = sqlite3.connect('file:/Users/zantao/.hermes/state.db?mode=ro', uri=True)
sid = 'cron_5128c85c245a_20260928_092433'
rows = con.execute("select id, role, content from messages where session_id=? order by id", (sid,)).fetchall()
found = False
for i, role, c in rows:
    if role == 'user' and c and '执行 Agent 运行' in c and '读取 orders' not in c:
        k = c.find('执行 Agent 运行')
        print('MSG', i, ':')
        print(c[max(0,k-200):k+400])
        found = True
        break
if not found:
    print('no injected stdout found in user msgs; checking tool msgs for stdout text')
    for i, role, c in rows:
        if c and '执行 Agent 运行: 2026-09-28' in c:
            k = c.find('执行 Agent 运行: 2026-09-28')
            print('MSG', i, role)
            print(c[max(0,k-100):k+400])
            break
