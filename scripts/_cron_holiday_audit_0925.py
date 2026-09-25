#!/usr/bin/env python3
"""盘点：哪些账户在非交易日 20260925 落了 NAV 行 / 成交记录"""
import sys
import sqlite3
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb')
state = sqlite3.connect(str(BASE / 'ledger.db'), timeout=30)
print('--- strategy_accounts @20260925 ---')
state.row_factory = sqlite3.Row
for r in state.execute("SELECT * FROM strategy_accounts WHERE date='20260925' ORDER BY account_id").fetchall():
    print(dict(r))
print('--- strategy_accounts @20260924 ---')
for r in state.execute("SELECT account_id,date,nav,daily_ret,market_ret,n_pos FROM strategy_accounts WHERE date='20260924' ORDER BY account_id").fetchall():
    print(dict(r))
print('--- trade_log @2026-09-25 ---')
for r in state.execute("SELECT id,code,direction,price,quantity,strategy,trade_time,notes FROM trade_log WHERE trade_date='2026-09-25'").fetchall():
    print(dict(r))
print('--- agent_auto 最近5笔 ---')
for r in state.execute("SELECT id,code,direction,price,quantity,trade_date,trade_time,notes FROM trade_log WHERE strategy='agent_auto' ORDER BY id DESC LIMIT 5").fetchall():
    print(dict(r))
state.close()
