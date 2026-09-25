import sqlite3
db = sqlite3.connect('/Users/zantao/.hermes/state.db')
def show(lo, hi, sid):
    rows = db.execute("SELECT id, role, substr(content,1,500), tool_name FROM messages WHERE session_id=? AND id BETWEEN ? AND ? AND content IS NOT NULL AND content != '' ORDER BY id", (sid, lo, hi)).fetchall()
    for mid, role, c, tn in rows:
        c = c.replace('\n', ' ⏎ ')
        print(f'--- {sid} [{mid}] {role} ({tn})')
        print(c[:500])
# QQ routing saga
show(267593, 267684, '20260923_183149_38d586')
