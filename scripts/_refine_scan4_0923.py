import sqlite3
db = sqlite3.connect('/Users/zantao/.hermes/state.db')
sid='20260923_183149_38d586'
# around 267755-267803: memory question + 98% change
rows = db.execute("SELECT id, role, substr(content,1,600), tool_name FROM messages WHERE session_id=? AND id BETWEEN 267750 AND 267812 AND (role!='assistant' OR content LIKE '%98%' OR content LIKE '%内存%' OR tool_name IS NOT NULL) ORDER BY id", (sid,)).fetchall()
for mid, role, c, tn in rows:
    if not c: c=''
    c = c.replace('\n',' ⏎ ')
    print(f'[{mid}] {role} ({tn}): {c[:450]}')
