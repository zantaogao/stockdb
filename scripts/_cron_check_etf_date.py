import sqlite3, os
base = os.path.expanduser('~/.hermes/stockdb')
for db, tbl in [('fund.db', 'fund_daily')]:
    p = os.path.join(base, db)
    try:
        c = sqlite3.connect(f'file:{p}?mode=ro', uri=True)
        print(db, tbl, c.execute(f'SELECT MAX(trade_date), COUNT(*) FROM {tbl}').fetchone())
        print('recent dates:', c.execute(f'SELECT trade_date, COUNT(*) FROM {tbl} GROUP BY trade_date ORDER BY trade_date DESC LIMIT 3').fetchall())
    except Exception as e:
        print(db, 'ERR', e)