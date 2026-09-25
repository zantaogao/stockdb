import sqlite3, json
db = sqlite3.connect('/Users/zantao/.hermes/state.db')
sid='20260923_202825_f48846'
rows = db.execute("SELECT id, role, substr(content,1,300) FROM messages WHERE session_id=? AND id>267979 AND content IS NOT NULL AND content!='' ORDER BY id DESC LIMIT 6", (sid,)).fetchall()
for mid, role, c in reversed(rows):
    print(f'[{mid}] {role}: {c[:280]}'.replace(chr(10),' ⏎ '))
print('===== history of edit run =====')
import urllib.request
h = json.load(urllib.request.urlopen('http://127.0.0.1:8188/history/5d99e968-41da-4fab-b12a-144034b5a112', timeout=10))
for pid, e in h.items():
    print(pid, 'status:', e.get('status'))
    for nid, o in e.get('outputs', {}).items():
        print(' out node', nid, o)
