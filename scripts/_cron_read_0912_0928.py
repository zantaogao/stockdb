import sqlite3
con = sqlite3.connect('file:/Users/zantao/.hermes/state.db?mode=ro', uri=True)
sid = 'cron_5128c85c245a_20260928_091230'
rows = con.execute("""select role, tool_name, substr(content,1,1200) from messages
  where session_id=? and (role!='assistant' or tool_calls is null or tool_calls='') order by id limit 8""", (sid,)).fetchall()
for role, tn, c in rows:
    print('===', role, tn, '===')
    print((c or '')[:1000])
