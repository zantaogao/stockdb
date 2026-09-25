import sqlite3, subprocess, datetime

sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
print('fusion_3f latest 3 dates:', sig.execute("SELECT date, COUNT(*) FROM fusion_3f_signals GROUP BY 1 ORDER BY 1 DESC LIMIT 3").fetchall())
print('new_factors latest 3:', sig.execute("SELECT date, COUNT(*) FROM new_factors GROUP BY 1 ORDER BY 1 DESC LIMIT 3").fetchall())

r = subprocess.run(['ps', '-p', '30568', '-o', 'etime,%cpu,stat,lstart'], capture_output=True, text=True)
print('PID 30568:', r.stdout or 'GONE')

import time
print('now:', time.strftime('%Y-%m-%d %H:%M:%S'))