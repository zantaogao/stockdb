#!/usr/bin/env /usr/bin/python3 -B
import sqlite3, datetime
c = sqlite3.connect('/Users/zantao/.hermes/state.db')
lo = datetime.datetime(2026, 9, 16, 6, 30).timestamp()
hi = datetime.datetime(2026, 9, 16, 12, 0).timestamp()
rows = list(c.execute(
    "SELECT m.timestamp, m.session_id, m.role, m.tool_name, "
    "substr(replace(coalesce(m.content,''), char(10), ' '), 1, 70), m.platform_message_id "
    "FROM messages m WHERE m.timestamp >= ? AND m.timestamp <= ? "
    "AND m.session_id LIKE '%qqbot%' ORDER BY m.timestamp", (lo, hi)))
for t, s, role, tn, txt, pmid in rows:
    print(datetime.datetime.fromtimestamp(t).strftime('%H:%M:%S'),
          s[-24:], (role or '')[:9], (tn or '')[:12], txt[:64])
