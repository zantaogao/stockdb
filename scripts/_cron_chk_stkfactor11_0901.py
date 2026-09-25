import sqlite3, os, time, glob
import subprocess

# signal chain outputs for today: fusion_3f_signals, fusion_center_signals, new_factors
sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
for t, dcol in [('fusion_3f_signals', 'signal_date'), ('fusion_center_signals', None), ('new_factors', 'trade_date')]:
    cols = [r[1] for r in sig.execute(f'PRAGMA table_info({t})')]
    d = dcol if dcol in cols else (cols[0] if 'date' in ''.join(cols) else None)
    try:
        col = dcol if dcol in cols else [c for c in cols if 'date' in c.lower()][0]
        latest = sig.execute(f'SELECT {col}, COUNT(*) FROM {t} GROUP BY 1 ORDER BY 1 DESC LIMIT 2').fetchall()
        print(t, latest)
    except Exception as e:
        print(t, 'ERR', str(e)[:80])

# when did the scripts last change / any crash lock?
print()
print('git?', os.path.exists('/Users/zantao/.hermes/stockdb/.git'))
# check if signal chain re-run happened tonight: look for a log in stockdb/logs today
today_files = []
for f in glob.glob('/Users/zantao/.hermes/stockdb/logs/*'):
    if time.localtime(os.path.getmtime(f)).tm_yday == time.localtime().tm_yday:
        today_files.append((time.strftime('%H:%M', time.localtime(os.path.getmtime(f))), os.path.basename(f)))
print('stockdb/logs modified today:', sorted(today_files))