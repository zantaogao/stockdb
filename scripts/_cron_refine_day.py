#!/usr/bin/env python3
"""09-15 当日用户/助手轨迹（排除 cron 会话），供 nightly refine。"""
import sqlite3, time, os, sys

day = sys.argv[1] if len(sys.argv) > 1 else "2026-09-15"
db = os.path.expanduser('~/.hermes/state.db')
c = sqlite3.connect('file:%s?mode=ro' % db, uri=True)
s = time.mktime(time.strptime(day + " 00:00:00", "%Y-%m-%d %H:%M:%S"))
e = time.mktime(time.strptime(day + " 23:59:59", "%Y-%m-%d %H:%M:%S"))
rows = c.execute("""select id,session_id,role,content,timestamp from messages
 where timestamp>=? and timestamp<? and role in ('user','assistant')
 and (display_kind is null or display_kind='') and (compacted is null or compacted=0)
 order by timestamp""", (s, e)).fetchall()
for mid, sid, role, content, ts in rows:
    if sid.startswith('cron_'):
        continue
    t = time.strftime('%m-%d %H:%M', time.localtime(ts))
    content = content or ''
    if role == 'user':
        if 'CONTEXT COMPACTION' in content or 'PRIOR CONTEXT' in content:
            print("\n[%s U%s] <compaction>" % (t, mid))
            continue
        print("\n[%s U%s] %s" % (t, mid, content[:700].replace('\n', ' | ')))
    else:
        if len(content.strip()) > 60:
            print("   [%s A%s] %s" % (t, mid, content[:280].replace('\n', ' | ')))
