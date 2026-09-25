#!/usr/bin/env python3
"""09-16 只读审计：策略账户本 tick 状态（不写库）。"""
import sqlite3, os, json, datetime

LED = os.path.expanduser('~/.hermes/stockdb/ledger.db')
con = sqlite3.connect(f'file:{LED}?mode=ro', uri=True)
c = con.cursor()

print('=== tables ===')
print([r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()])

print('\n=== strategy_accounts 近3日 ===')
try:
    for r in c.execute("SELECT account_id,date,nav,daily_ret,n_pos FROM strategy_accounts WHERE REPLACE(date,'-','')>='20260914' ORDER BY account_id,date").fetchall():
        print(' ', r)
except Exception as e:
    print(' ERR', e)

print('\n=== strategy_positions 按账户 ===')
try:
    for r in c.execute("SELECT account_id, COUNT(*), ROUND(SUM(shares*avg_cost),0) FROM strategy_positions GROUP BY account_id").fetchall():
        print(' ', r)
except Exception as e:
    print(' ERR', e)

print('\n=== 今日(09-16) 策略流水 ===')
try:
    cols = [d[1] for d in c.execute("PRAGMA table_info(strategy_trades)").fetchall()]
    print(' cols:', cols)
    for r in c.execute("SELECT * FROM strategy_trades WHERE REPLACE(date,'-','')='20260916' ORDER BY account_id").fetchall():
        print(' ', r)
except Exception as e:
    print(' ERR', e)

print('\n=== 最近5笔(任意日) ===')
try:
    for r in c.execute("SELECT * FROM strategy_trades ORDER BY REPLACE(date,'-','') DESC, rowid DESC LIMIT 5").fetchall():
        print(' ', r)
except Exception as e:
    print(' ERR', e)

print('\n=== 09-15 流水(上一交易日) ===')
try:
    for r in c.execute("SELECT * FROM strategy_trades WHERE REPLACE(date,'-','')='20260915'").fetchall():
        print(' ', r)
except Exception as e:
    print(' ERR', e)

print('\n=== 冷却表(若存在) ===')
for t in ('cmmr_cooldown','strategy_cooldown'):
    try:
        rows = c.execute(f"SELECT * FROM {t}").fetchall()
        print(f' {t}:', rows[:20])
    except Exception as e:
        print(f' {t}: ERR {e}')

print('\n=== defense_state ===')
try:
    print(c.execute("SELECT * FROM defense_state").fetchall())
except Exception as e:
    print(' ERR', e)
con.close()
