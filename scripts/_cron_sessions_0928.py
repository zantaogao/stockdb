import sqlite3
con = sqlite3.connect('file:/Users/zantao/.hermes/state.db?mode=ro', uri=True)
rows = con.execute("""
  select id, source, title, started_at, message_count from sessions
  order by started_at desc limit 15
""").fetchall()
for r in rows: print(r)
print('---meta---')
for r in con.execute("select key, substr(value,1,120) from state_meta limit 20").fetchall():
    print(r)
