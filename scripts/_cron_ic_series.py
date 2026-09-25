#!/usr/bin/env python3
# _cron_ic_series 分模型IC近12信号日（只读）
import sqlite3, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('file:signals.db?mode=ro', uri=True)
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print('tables:', [t for t in tabs if 'ic' in t.lower()])
for t in ['ic_daily','fusion_ic_daily','center_dual_ic_daily','ic_window']:
    if t not in tabs:
        print(t, 'MISSING'); continue
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})").fetchall()]
    print('----', t, cols)
    try:
        for r in c.execute(f"SELECT * FROM {t} ORDER BY 1 DESC LIMIT 12").fetchall():
            print(r)
    except Exception as e:
        print('ERR', e)
