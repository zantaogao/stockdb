import sqlite3, glob

sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
for t, c in [('new_factors', 'date'), ('fusion_3f_signals', 'date'), ('fusion_center_signals', 'date')]:
    d = sig.execute(f"SELECT COUNT(*) FROM {t} WHERE REPLACE({c},'-','')='20260901'").fetchone()[0]
    latest = sig.execute(f'SELECT MAX({c}) FROM {t}').fetchone()[0]
    print(f'{t}: 20260901={d} rows, latest={latest}')

# Lock state: who holds tushare.db.lock? lsof
import subprocess
r = subprocess.run(['lsof', '/Users/zantao/.hermes/stockdb/tushare.db.lock'], capture_output=True, text=True)
print('lsof lock:', r.stdout or '(none)')

# signal_agent stuck process still alive?
r = subprocess.run(['ps', '-p', '30568', '-o', 'etime,%cpu,stat'], capture_output=True, text=True)
print('signal_agent 30568:', r.stdout.strip() or 'GONE')