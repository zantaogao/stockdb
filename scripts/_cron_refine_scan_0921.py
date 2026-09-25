import sqlite3
c = sqlite3.connect('file:/Users/zantao/.hermes/state.db?mode=ro', uri=True)
# user messages in today's interactive sessions
for sid in ('20260921_113804_32d805','20260921_123021_02a5f8'):
    print('==== USER MSGS', sid)
    for r in c.execute("SELECT id, timestamp, substr(content,1,400) FROM messages WHERE session_id=? AND role='user' ORDER BY id", (sid,)):
        print(r)
print('==== ERROR-ish tool results today')
for r in c.execute("""SELECT session_id, id, tool_name, substr(content,1,300) FROM messages
  WHERE role='tool' AND timestamp>=1789958400
    AND (content LIKE '%error%' OR content LIKE '%Error%' OR content LIKE '%失败%' OR content LIKE '%Traceback%' OR content LIKE '%refused%' OR content LIKE '%not a database%' OR content LIKE '%not found%')
  ORDER BY session_id, id"""):
    print(r)
