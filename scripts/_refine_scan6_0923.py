import sqlite3
db = sqlite3.connect('/Users/zantao/.hermes/state.db')
sid='20260923_202825_f48846'
rows = db.execute("SELECT id, role, substr(content,1,400), timestamp FROM messages WHERE session_id=? AND content IS NOT NULL AND content!='' ORDER BY id DESC LIMIT 10", (sid,)).fetchall()
import datetime
for mid, role, c, ts in reversed(rows):
    t = datetime.datetime.fromtimestamp(ts).strftime('%H:%M:%S')
    print(f'[{mid}] {t} {role}: '+c[:300].replace('\n',' ⏎ '))
