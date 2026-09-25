import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
for t in ['signal_history','new_factors','flow_alpha','vol_adj','fusion_3f_signals','fusion_center_signals']:
    cols = [r[1] for r in c.execute('PRAGMA table_info(%s)' % t)]
    d = 'date' if 'date' in cols else 'trade_date'
    q = "SELECT COUNT(*), MAX(REPLACE(%s,'-','')) FROM %s WHERE REPLACE(%s,'-','')>='20260831'" % (d, t, d)
    print(t, c.execute(q).fetchone())