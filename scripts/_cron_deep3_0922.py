#!/usr/bin/env python3
import duckdb, sqlite3, os, json
from collections import defaultdict
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
tdb = duckdb.connect('tushare.db', read_only=True)
def sec(t): print('\n===== '+t+' =====')

sec('board_daily 列与样本')
print([c[0] for c in tdb.execute("DESCRIBE board_daily").fetchall()])
for r in tdb.execute("SELECT * FROM board_daily LIMIT 3").fetchall(): print(str(r)[:200])
print('board types:', tdb.execute("SELECT DISTINCT board_type, COUNT(*) FROM board_daily GROUP BY 1").fetchall() if 'board_type' in str(tdb.execute('DESCRIBE board_daily').fetchall()) else 'n/a')

sec('signals.db 表')
sig = sqlite3.connect('signals.db')
print([r[0] for r in sig.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()])

sec('factors.db 表')
try:
    fac = sqlite3.connect('file:factors.db?mode=ro', uri=True)
    print([r[0] for r in fac.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()])
except Exception as e: print(e)
