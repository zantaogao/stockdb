import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
for t in ['fusion_3f_signals','signal_history']:
    cols = [x[1] for x in c.execute(f'PRAGMA table_info({t})').fetchall()]
    print(t, cols)
    for code in ['600893','600096']:
        rows = c.execute(f"SELECT * FROM {t} WHERE stock_code LIKE ? ORDER BY date DESC LIMIT 2", (f'%{code}%',)).fetchall()
        print(' ', code, rows)
