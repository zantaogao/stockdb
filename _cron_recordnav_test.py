#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 record_nav 修复：盘中多次运行时 returns 应始终 vs 昨天基准"""
import sys, os, json
sys.path.insert(0, os.path.expanduser('~/.hermes/stockdb'))
from core.unified_account import Account, AccountStore

# 内存构造账户，不碰磁盘
acct = Account(account_id='test_nav', name='test', initial_capital=1000000.0)
acct.cash = 1000000.0

# 模拟：昨天 NAV 记录
acct.nav_history.append({'date': '2026-08-13', 'nav': 990000.0, 'returns': -1.0})

# 今天盘中 3 次运行（价格不同）
class FakePos:
    def __init__(self, code, shares, avg_cost):
        self.code = code; self.shares = shares; self.avg_cost = avg_cost

acct.positions = [FakePos('600001', 1000, 10.0)]

# 用 patch 后的 record_nav（price_map 模拟实时价）
r1 = acct.record_nav({'600001': 10.5})   # 盘中1: 现价10.5 → NAV 1010500, vs 昨天 990000 → +2.07%
r2 = acct.record_nav({'600001': 10.6})   # 盘中2: 现价10.6 → NAV 1010600, vs 昨天 → +2.08%（修复前会 vs r1 → +0.01%）
r3 = acct.record_nav({'600001': 10.55})  # 盘中3: 现价10.55 → NAV 1010550, vs 昨天 → +2.07%

print("修复后 returns（应全部≈+2.07%，vs 昨天基准）:")
for i, r in enumerate([r1, r2, r3], 1):
    print(f"  盘中{i}: date={r['date']} nav={r['nav']:.2f} returns={r['returns']:.4f}%")
    assert abs(r['returns'] - 2.07) < 0.05, f"returns 异常: {r['returns']}"

# 验证 nav_history 只有今天一条（同 key 更新）
today_entries = [h for h in acct.nav_history if h['date'] == r3['date']]
print(f"\n今天 nav_history 条数: {len(today_entries)} (应=1)")
assert len(today_entries) == 1

print("\n✅ record_nav 修复验证通过：盘中多次运行 returns 始终 vs 昨天，不产生瞬变值")
