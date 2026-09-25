import sqlite3
c = sqlite3.connect('file:/Users/zantao/.hermes/state.db?mode=ro', uri=True)
# final responses of cron sessions with errors
for sid in ('cron_051af215dc32_20260921_111525','cron_051af215dc32_20260921_140556','cron_1eb1d98a7074_20260921_174358','cron_46176067da46_20260921_220'):
    for r in c.execute("SELECT substr(content,1,400) FROM messages WHERE session_id=? AND role='assistant' AND length(content)>80 ORDER BY id DESC LIMIT 1", (sid,)):
        print('>>', sid); print(r[0]); print('---')
# ETF session ids today
print(list(c.execute("SELECT id FROM sessions WHERE id LIKE 'cron_1eb1d98a%' AND started_at>=1789958400")))
