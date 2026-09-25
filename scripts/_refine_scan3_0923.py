import sqlite3
db = sqlite3.connect('/Users/zantao/.hermes/state.db')
sid='20260923_202825_f48846'
rows = db.execute("SELECT id, role, substr(content,1,400), tool_name FROM messages WHERE session_id=? AND id>267917 ORDER BY id", (sid,)).fetchall()
for mid, role, c, tn in rows:
    if not c: c=''
    c = c.replace('\n',' ⏎ ')
    print(f'[{mid}] {role} ({tn}): {c[:400]}')
