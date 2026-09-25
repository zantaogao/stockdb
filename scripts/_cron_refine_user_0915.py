#!/usr/bin/env python3
"""09-15 用户消息 + 助手收尾（排除 cron 会话、压缩块），供 nightly refine 复盘。"""
import sqlite3, time, os

db = os.path.expanduser('~/.hermes/state.db')
c = sqlite3.connect('file:%s?mode=ro' % db, uri=True)
start = time.mktime(time.strptime("2026-09-14 20:00:00", "%Y-%m-%d %H:%M:%S"))
end = time.mktime(time.strptime("2026-09-15 23:59:59", "%Y-%m-%d %H:%M:%S"))
rows = c.execute("""select id, session_id, role, content, timestamp from messages
 where timestamp >= ? and timestamp < ? and role in ('user','assistant')
 and (display_kind is null or display_kind='')
 and (compacted is null or compacted = 0)
 order by timestamp""", (start, end)).fetchall()

seen = set()
for mid, sid, role, content, ts in rows:
    if sid.startswith('cron_'):
        continue
    t = time.strftime('%m-%d %H:%M', time.localtime(ts))
    content = content or ''
    if role == 'user':
        if 'CONTEXT COMPACTION' in content:
            print("[%s U %s] <compaction summary>" % (t, mid))
            continue
        print("\n[%s U %s] %s" % (t, mid, content[:800]))
    else:
        key = (sid, mid // 3)
        if len(content.strip()) > 60:
            print("    [%s A %s] %s" % (t, mid, content[:400].replace('\n', ' | ')))
