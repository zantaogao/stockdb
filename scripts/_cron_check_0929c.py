import sqlite3
con=sqlite3.connect('file:/Users/zantao/.hermes/stockdb/signals.db?mode=ro',uri=True)
cur=con.cursor()
# any BUY/SELL logged today
for t in ['signal_history','tdx_signal_log']:
    cols=[c[1] for c in cur.execute(f'PRAGMA table_info("{t}")').fetchall()]
    print(t,cols)
rows=cur.execute("select distinct action from tdx_signal_log where date='2026-09-29'").fetchall()
print('today actions:',rows)
# strategy account nav store
con2=sqlite3.connect('file:/Users/zantao/.hermes/stockdb/factors.db?mode=ro',uri=True)
tabs=[r[0] for r in con2.execute("select name from sqlite_master where type='table'").fetchall()]
print('factors.db tabs:',tabs[:30])
