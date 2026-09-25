#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查 strategy_accounts 日收益异常值"""
import sqlite3, os
BASE = os.path.expanduser('~/.hermes/stockdb')
s = sqlite3.connect(os.path.join(BASE, 'state.db'))
s.row_factory = sqlite3.Row

print("--- strategy_accounts 表结构 ---")
cols = [r[1] for r in s.execute("PRAGMA table_info(strategy_accounts)").fetchall()]
print("列:", cols)

print("\n--- 各账户数据量 + 日期范围 ---")
for r in s.execute("SELECT account_id, COUNT(*), MIN(date), MAX(date) FROM strategy_accounts GROUP BY 1").fetchall():
    print(f"  {r['account_id']}: {r[1]} 行, {r[2]} ~ {r[3]}")

print("\n--- 日收益极端值（|daily_ret| > 50%）---")
rows = s.execute("""
    SELECT account_id, date, nav, daily_ret, market_ret 
    FROM strategy_accounts 
    WHERE ABS(daily_ret) > 50 OR ABS(market_ret) > 50
    ORDER BY ABS(daily_ret) DESC LIMIT 20
""").fetchall()
for r in rows:
    print(f"  {r['account_id']:12s} {r['date']}  nav={r['nav']:>12.2f}  daily_ret={r['daily_ret']:>8.2f}%  market_ret={r['market_ret']:>8.2f}%")

print("\n--- 正常值参考（最新几行）---")
for r in s.execute("SELECT account_id, date, nav, daily_ret, market_ret FROM strategy_accounts ORDER BY date DESC, account_id LIMIT 10").fetchall():
    print(f"  {r['account_id']:12s} {r['date']}  nav={r['nav']:>12.2f}  daily_ret={r['daily_ret']:>8.2f}%  market_ret={r['market_ret']:>8.2f}%")
s.close()
