import sqlite3
db = sqlite3.connect('/Users/zantao/.hermes/state.db')
chain = ['20260923_160941_fce4d2','20260923_164659_089e15','20260923_173227_915893','20260923_180238_8dd3d2','20260923_183149_38d586','20260923_202825_f48846']
for sid in chain:
    rows = db.execute("SELECT id, content FROM messages WHERE session_id=? AND role='user' ORDER BY id", (sid,)).fetchall()
    print('='*20, sid, len(rows), 'user msgs')
    for mid, c in rows:
        c = (c or '').strip().replace('\n', ' ⏎ ')
        print(f'[{mid}] {c[:280]}')
