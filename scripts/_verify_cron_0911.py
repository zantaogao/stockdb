import sqlite3, os, glob

# 1. tushare backup dirs contents
for d in sorted(glob.glob(os.path.expanduser('~/.hermes/stockdb/db_backups/tushare/2026*')))[-3:]:
    print(d, '->', os.listdir(d))

# 2. strategy_accounts NAV freshness + ca_run_log
c = sqlite3.connect(os.path.expanduser('~/.hermes/stockdb/ledger.db'), timeout=5)
print('strategy_accounts latest:', c.execute("SELECT MAX(REPLACE(date,'-','')) FROM strategy_accounts").fetchone()[0])
print('ca_run_log 20260911:', c.execute("SELECT status,n_ex,n_hit FROM ca_run_log WHERE run_date='20260911'").fetchall())
c.close()
