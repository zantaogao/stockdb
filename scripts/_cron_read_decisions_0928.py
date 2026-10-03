import sqlite3, json
con = sqlite3.connect('file:/Users/zantao/.hermes/state.db?mode=ro', uri=True)
for sid in ('cron_2e55e47d3ccd_20260928_091030','cron_2e55e47d3ccd_20260928_090028','cron_2e55e47d3ccd_20260928_092032'):
    rows = con.execute("""select role, tool_name, content from messages where session_id=? order by id""", (sid,)).fetchall()
    print('#####', sid, 'n=', len(rows))
    for role, tn, c in rows:
        if role == 'tool':
            print('--- TOOL OUTPUT ---')
            print((c or '')[:1500])
        elif role == 'assistant' and c and '✅' in c or (c and '⚠' in c):
            print('--- ASSISTANT FINAL ---')
            print((c or '')[:500])
