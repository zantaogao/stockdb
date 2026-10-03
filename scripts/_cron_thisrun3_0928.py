import sqlite3
con = sqlite3.connect('file:/Users/zantao/.hermes/state.db?mode=ro', uri=True)
sid = 'cron_5128c85c245a_20260928_092433'
rows = con.execute("select id, role, substr(content,1,300) from messages where session_id=? order by id limit 4", (sid,)).fetchall()
for i, role, c in rows:
    print('===', i, role, '===')
    print(c or '')
