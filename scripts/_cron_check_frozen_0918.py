import sqlite3, json, glob, os
db = os.path.expanduser('~/.hermes/stockdb/ledger.db')
c = sqlite3.connect(db)
try:
    rows = c.execute("SELECT account_id, MAX(trade_date), COUNT(*) FROM trade_log WHERE account_id IN ('fusion3f','fusion_dual') GROUP BY account_id").fetchall()
    print('trade_log last dates:', rows)
except Exception as e:
    print('trade_log err:', e)
try:
    rows = c.execute("SELECT account_id, date, nav FROM strategy_nav WHERE account_id IN ('fusion3f','fusion_dual') ORDER BY date DESC LIMIT 6").fetchall()
    print('nav tail:', rows)
except Exception as e:
    print('nav err:', e)
# closed flags in the daily script
import subprocess
out = subprocess.run(['grep','-n','-E',"closed|fusion3f|fusion_dual", os.path.expanduser('~/.hermes/stockdb/scripts/strategy_accounts_daily.py')], capture_output=True, text=True).stdout
print(out[:1500])
