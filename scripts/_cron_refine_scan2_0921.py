import sqlite3
c = sqlite3.connect('file:/Users/zantao/.hermes/state.db?mode=ro', uri=True)
print('==== assistant msgs in 113804 around user corrections (260768+)')
for r in c.execute("SELECT id, role, substr(content,1,500) FROM messages WHERE session_id='20260921_113804_32d805' AND id BETWEEN 260767 AND 260826 AND role IN ('assistant','user') ORDER BY id"):
    print(r); print('---')
