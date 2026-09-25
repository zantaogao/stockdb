#!/usr/bin/env python3
import duckdb, sqlite3, os
from collections import defaultdict
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
tdb = duckdb.connect('tushare.db', read_only=True)
sig = sqlite3.connect('signals.db')
led = sqlite3.connect('ledger.db')
def sec(t): print('\n===== '+t+' =====')

sec('表名探查')
print([r[0] for r in tdb.execute("SHOW TABLES").fetchall()])

sec('meta列')
print([c[1] for c in led.execute("PRAGMA table_info(strategy_accounts_meta)").fetchall()])
for r in led.execute("SELECT * FROM strategy_accounts_meta").fetchall(): print(str(r)[:200])
