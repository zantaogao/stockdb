import sqlite3
c = sqlite3.connect('file:/Users/zantao/.hermes/state.db?mode=ro', uri=True)
print('==== tail of 113804')
for r in c.execute("SELECT id, role, substr(content,1,700) FROM messages WHERE session_id='20260921_113804_32d805' AND id>=260823 AND role IN ('assistant','user') ORDER BY id"):
    print(r); print('---')
print('==== 123021 tail')
for r in c.execute("SELECT id, role, substr(content,1,700) FROM messages WHERE session_id='20260921_123021_02a5f8' AND role IN ('assistant','user') ORDER BY id DESC LIMIT 8"):
    print(r); print('---')
