import sqlite3, json
c = sqlite3.connect('file:/Users/zantao/.hermes/state.db?mode=ro', uri=True)
print('46176067 sessions today:', list(c.execute("SELECT id,started_at FROM sessions WHERE id LIKE 'cron_46176067%' AND started_at>=1789958400")))
# last assistant msg of 20:30 health check
for (sid,) in c.execute("SELECT id FROM sessions WHERE id='cron_e90d037af31b_20260921_203002'"):
    for r in c.execute("SELECT substr(content,1,1500) FROM messages WHERE session_id=? AND role='assistant' AND length(content)>50 ORDER BY id DESC LIMIT 1", (sid,)):
        print(r[0])
# account_balance now
import subprocess
print(subprocess.run(['/usr/bin/sqlite3','/Users/zantao/.hermes/stockdb/ledger.db','select cash_balance,total_value,last_update from account_balance;'],capture_output=True,text=True).stdout)
