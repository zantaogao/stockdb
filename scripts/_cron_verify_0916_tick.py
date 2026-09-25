#!/usr/bin/env python3
"""核查本轮 09:45 落库情况：补缺口 603186 100股@250.08（reg10_solo）+ 持仓/NAV。"""
import sqlite3, os
LED = sqlite3.connect(os.path.expanduser('~/.hermes/stockdb/ledger.db'))

for t in ('strategy_positions', 'trade_log', 'strategy_nav'):
    cur = LED.execute(f"PRAGMA table_info({t})")
    print(t, "->", [r[1] for r in cur.fetchall()])

print("\n=== reg10_solo 持仓 ===")
cur = LED.execute("SELECT * FROM strategy_positions WHERE account_id='reg10_solo'")
cols = [d[0] for d in cur.description]
print(cols)
for r in cur.fetchall():
    print(r)

print("\n=== trade_log 表结构样本 ===")
cur = LED.execute("SELECT * FROM trade_log ORDER BY rowid DESC LIMIT 6")
cols = [d[0] for d in cur.description]
print(cols)
for r in cur.fetchall():
    print(r)

print("\n=== cmmr 策略持仓 ===")
cur = LED.execute("SELECT * FROM strategy_positions WHERE account_id='cmmr'")
cols = [d[0] for d in cur.description]
print(cols)
for r in cur.fetchall():
    print(r)

print("\n=== 各账户今日 NAV 明细 ===")
cur = LED.execute("SELECT account_id, date, nav, cash, pos_value, daily_ret, n_pos, created_at FROM strategy_accounts WHERE replace(date,'-','')='20260916' ORDER BY account_id")
for r in cur.fetchall():
    print(r)
