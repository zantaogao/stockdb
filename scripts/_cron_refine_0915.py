#!/usr/bin/env python3
"""List user/assistant messages from 2026-09-15 (CST) across CLI/QQ sessions for nightly refine."""
import sqlite3, time, os, sys

db = os.path.expanduser('~/.hermes/state.db')
c = sqlite3.connect('file:%s?mode=ro' % db, uri=True)
cols = [r[1] for r in c.execute("PRAGMA table_info(messages)")]
print("messages cols:", cols)
start = time.mktime(time.strptime("2026-09-15 00:00:00", "%Y-%m-%d %H:%M:%S"))
end = time.mktime(time.strptime("2026-09-15 23:59:59", "%Y-%m-%d %H:%M:%S"))

sel = "select id, session_id, role, substr(replace(content,char(10),' | '),1,600), timestamp from messages where timestamp >= ? and timestamp < ? and role in ('user','assistant') and (display_kind is null or display_kind='') order by timestamp"
try:
    rows = c.execute(sel, (start, end)).fetchall()
except Exception as e:
    print("ERR", e)
    sys.exit(1)

print("total rows:", len(rows))
cur = None
for mid, sid, role, content, ts in rows:
    t = time.strftime('%H:%M', time.localtime(ts))
    if sid != cur:
        cur = sid
        print("\n=== SESSION %s ===" % sid)
    if role == 'user':
        print("[%s U %s] %s" % (t, mid, content[:500]))
    else:
        print("  [%s A %s] %s" % (t, mid, (content or '')[:200]))
