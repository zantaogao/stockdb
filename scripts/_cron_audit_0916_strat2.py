#!/usr/bin/env python3
"""09-16 只读审计 2：策略流水/冷却/meta + cron 执行状态。"""
import sqlite3, os, glob

LED = os.path.expanduser('~/.hermes/stockdb/ledger.db')
con = sqlite3.connect(f'file:{LED}?mode=ro', uri=True)
c = con.cursor()

print('=== trade_log cols ===')
print([d[1] for d in c.execute("PRAGMA table_info(trade_log)").fetchall()])
print('\n=== trade_log 09-15/09-16 ===')
for r in c.execute("SELECT * FROM trade_log WHERE REPLACE(trade_date,'-','') IN ('20260915','20260916') ORDER BY REPLACE(trade_date,'-','')").fetchall():
    print(' ', r)

print('\n=== strategy_positions cols ===')
print([d[1] for d in c.execute("PRAGMA table_info(strategy_positions)").fetchall()])
print('\n=== strategy_positions reg10_solo ===')
for r in c.execute("SELECT * FROM strategy_positions WHERE account_id='reg10_solo'").fetchall():
    print(' ', r)

print('\n=== strategy_accounts_meta ===')
print([d[1] for d in c.execute("PRAGMA table_info(strategy_accounts_meta)").fetchall()])
for r in c.execute("SELECT * FROM strategy_accounts_meta").fetchall():
    print(' ', r)

print('\n=== trade_cooldown ===')
try:
    print([d[1] for d in c.execute("PRAGMA table_info(trade_cooldown)").fetchall()])
    for r in c.execute("SELECT * FROM trade_cooldown ORDER BY rowid DESC LIMIT 15").fetchall():
        print(' ', r)
except Exception as e:
    print(' ERR', e)

print('\n=== strategy_accounts ALL dates per account (count) ===')
for r in c.execute("SELECT account_id, COUNT(*), MIN(date), MAX(date) FROM strategy_accounts GROUP BY account_id").fetchall():
    print(' ', r)
con.close()

print('\n=== sim_accounts/*.json mtime ===')
for p in sorted(glob.glob(os.path.expanduser('~/.hermes/stockdb/sim_accounts/*.json'))):
    st = os.stat(p)
    import datetime
    print(f'  {os.path.basename(p):30s} {datetime.datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M}  {st.st_size}B')
