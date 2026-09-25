import sqlite3, json

c = sqlite3.connect('/Users/zantao/.hermes/state.db')
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print('tables:', tables[:20])
# find messages table
for t in tables:
    if 'mess' in t.lower():
        cols = [r[1] for r in c.execute(f'PRAGMA table_info({t})')]
        print(t, 'cols:', cols)
        # find session
        try:
            rows = c.execute(f"SELECT DISTINCT session_id FROM {t} WHERE session_id LIKE '%099aee371ab5%'").fetchall()
            print('sessions:', rows)
        except Exception as e:
            print(e)