#!/usr/bin/env python3
"""cron 复核：agent_auto 今日成交与持仓（只读）"""
import sys
from pathlib import Path
BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))
import sqlite3
from core.unified_account import AccountStore

state = sqlite3.connect(str(BASE / 'ledger.db'), timeout=30)
print('今日 agent_auto 成交:')
for r in state.execute("SELECT id,trade_time,direction,code,name,price,quantity,amount FROM trade_log WHERE strategy='agent_auto' AND trade_date='2026-09-16' ORDER BY id"):
    print(' ', r)
print('今日 agent_auto 单数:', state.execute("SELECT COUNT(*), COALESCE(SUM(CASE WHEN direction='BUY' THEN amount ELSE 0 END),0) FROM trade_log WHERE strategy='agent_auto' AND trade_date='2026-09-16'").fetchone())
print('strategy_accounts 最新:', state.execute("SELECT * FROM strategy_accounts WHERE account_id='agent_auto' ORDER BY date DESC LIMIT 1").fetchone())
acct = AccountStore().load('agent_auto')
print(f"\n现金 {acct.cash:,.2f}  持仓 {len(acct.positions)} 只")
for p in acct.positions:
    print(f"  {p.code} {p.name} {p.shares}股 成本{p.avg_cost} 买入{p.buy_date} 峰值{p.peak_price}")
state.close()
