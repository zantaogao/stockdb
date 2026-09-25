#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全量检查 strategy_accounts 所有行 + NAV 序列连续性"""
import sqlite3, os
BASE = os.path.expanduser('~/.hermes/stockdb')
s = sqlite3.connect(os.path.join(BASE, 'state.db'))
s.row_factory = sqlite3.Row

print("--- 全量数据（按账户+日期）---")
rows = s.execute("""
    SELECT account_id, date, nav, cash, pos_value, daily_ret, market_ret, n_pos
    FROM strategy_accounts ORDER BY account_id, date
""").fetchall()
cur = None
for r in rows:
    if r['account_id'] != cur:
        cur = r['account_id']
        print(f"\n[{cur}]")
    # NAV 环比（检查 NAV 突变）
    print(f"  {r['date']}  nav={r['nav']:>12.2f}  cash={r['cash']:>10.2f}  pos={r['pos_value']:>10.2f}  "
          f"daily_ret={r['daily_ret']:>8.2f}%  mkt={r['market_ret']:>8.2f}%  n_pos={r['n_pos']}")

# 手动验证 NAV 环比 vs daily_ret 一致性
print("\n--- NAV 环比 vs daily_ret 一致性（应近似相等）---")
rows2 = s.execute("""
    SELECT account_id, date, nav, daily_ret FROM strategy_accounts ORDER BY account_id, date
""").fetchall()
from collections import defaultdict
seq = defaultdict(list)
for r in rows2:
    seq[r['account_id']].append((r['date'], r['nav'], r['daily_ret']))
for aid, items in seq.items():
    for i in range(1, len(items)):
        d0, nav0, _ = items[i-1]
        d1, nav1, dr = items[i]
        chg = (nav1/nav0 - 1) * 100 if nav0 else 0
        match = "OK" if abs(chg - dr) < 0.5 else "⚠️ 不一致"
        print(f"  {aid:12s} {d0}→{d1}: nav 环比 {chg:+.2f}% vs daily_ret {dr:+.2f}%  {match}")
s.close()
