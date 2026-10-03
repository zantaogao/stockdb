import sqlite3
con = sqlite3.connect('file:/Users/zantao/.hermes/state.db?mode=ro', uri=True)
sid = 'cron_5128c85c245a_20260928_092433'
rows = con.execute("select id, role, substr(content,1,400) from messages where session_id=? and role='tool' order by id", (sid,)).fetchall()
hits = [r for r in rows if r[2] and '非交易时段' in r[2]]
for h in hits[:3]:
    print(h[0], h[2][:300])
    print('...')
