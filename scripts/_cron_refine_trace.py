"""从 state.db 提取今日(默认 2026-09-14) 的人类会话轨迹摘要，供 nightly-refine 回看。
只读，不改任何东西。"""
import sqlite3, os, sys, datetime as dt, re

TZ = dt.timezone(dt.timedelta(hours=8))
DAY = sys.argv[1] if len(sys.argv) > 1 else '2026-09-14'
DB = os.path.expanduser('~/.hermes/state.db')

d = dt.datetime.strptime(DAY, '%Y-%m-%d').replace(tzinfo=TZ)
t0, t1 = d.timestamp(), (d + dt.timedelta(days=1)).timestamp()

c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
print("== schema messages ==")
print([r[1] for r in c.execute("PRAGMA table_info(messages)")])
print("== schema sessions ==")
print([r[1] for r in c.execute("PRAGMA table_info(sessions)")])

rows = c.execute("""
  select s.id, s.source, s.started_at, count(*) as n
  from messages m join sessions s on s.id=m.session_id
  where s.source in ('cli','tui') and m.timestamp>=? and m.timestamp<?
  group by s.id, s.source, s.started_at order by s.started_at
""", (t0, t1)).fetchall()
print(f"\n== CLI/TUI sessions on {DAY} ==")
for sid, src, st, n in rows:
    print(f"  {sid} {src} start={dt.datetime.fromtimestamp(st, TZ):%H:%M} msgs={n}")

print(f"\n== user messages (cli/tui) on {DAY} ==")
msgs = c.execute("""
  select m.session_id, m.id, m.role, m.timestamp, m.content
  from messages m join sessions s on s.id=m.session_id
  where s.source in ('cli','tui') and m.timestamp>=? and m.timestamp<?
    and m.role='user' and m.compacted=0
  order by m.id
""", (t0, t1)).fetchall()
for sid, mid, role, ts, content in msgs:
    t = (content or '').strip().replace('\n', ' \\n ')
    if t.startswith('[CONTEXT COMPACTION'): t = '[COMPACTION]'
    print(f"[{dt.datetime.fromtimestamp(float(ts), TZ):%H:%M}] {sid[-6:]} #{mid}: {t[:400]}")

print(f"\n== assistant messages containing failure signals on {DAY} ==")
PAT = re.compile(r'(失败|报错|Error|error|traceback|重试|又|还是不行|超时|timeout|卡住|Approval|拒绝)')
ams = c.execute("""
  select m.session_id, m.id, m.timestamp, m.content
  from messages m join sessions s on s.id=m.session_id
  where s.source in ('cli','tui') and m.timestamp>=? and m.timestamp<?
    and m.role='assistant' and m.compacted=0 and m.content is not null
  order by m.id
""", (t0, t1)).fetchall()
for sid, mid, ts, content in ams:
    if PAT.search(content):
        print(f"[{dt.datetime.fromtimestamp(float(ts), TZ):%H:%M}] {sid[-6:]} #{mid}: {content.strip()[:300]}")
