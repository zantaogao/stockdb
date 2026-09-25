#!/usr/bin/env python3
"""一次性：建 agent_auto 策略账户（100万，2026-09-04 用户拍板）。跑完留档可重跑（幂等 UPSERT）。"""
import sys
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from core.unified_account import AccountStore, Account

store = AccountStore()
acct = Account('agent_auto', 'Agent全权', 1_000_000.0,
               config={'last_rebalance_date': '2026-09-04'}, created_at='2026-09-04')
acct.cash = 1_000_000.0
store.save(acct)
a = store.load('agent_auto')
print(f"建户验证: id={a.id} name={a.name} capital={a.initial_capital} cash={a.cash} pos={len(a.positions)}")