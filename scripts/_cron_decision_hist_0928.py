import sqlite3, json
con = sqlite3.connect('file:/Users/zantao/.hermes/state.db?mode=ro', uri=True)
sids = [r[0] for r in con.execute("select id from sessions where id like 'cron_2e55e47d3ccd_202609%' order by id desc limit 12").fetchall()]
print(sids)
for sid in sids:
    rows = con.execute("select content from messages where session_id=? and role='tool' and content like '%大盘%'", (sid,)).fetchall()
    trades = [c for c, in rows if '生成' in c or '📈' in c or '📉' in c or '→' in c]
    final = con.execute("select content from messages where session_id=? and role='assistant' and content is not null and length(content)>5 order by id desc limit 1", (sid,)).fetchone()
    print('###', sid, '| final:', (final[0][:120] if final else None))
    for t in trades[:2]:
        k = t.find('大盘')
        print('   stdout-excerpt:', t[max(0,k-30):k+400].replace('\\n','\n   '))
