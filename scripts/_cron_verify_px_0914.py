#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复核 14:45 tick 的 '无实时价' 块：是真停牌还是 Sina 批量截断；并复算 fusion_center NAV"""
import sys, os, sqlite3, datetime
sys.path.insert(0, os.path.expanduser("~/.hermes/stockdb"))
os.chdir(os.path.expanduser("~/.hermes/stockdb"))
from core.prices import fetch_prices_batch

print("now:", datetime.datetime.now().strftime("%H:%M:%S"))
c = sqlite3.connect("ledger.db")

bad = "000032 000421 000720 000897 000990 002187 002199 002469 003017 300105 300281 300321 300349 300474 301113 600100 600231 600512 600563 600609 600731 600790 600841 601319 601886 601996 603103 603955 688099".split()

print("\n=== 逐只单独拉 Sina 实时价（那 29 只）===")
got = fetch_prices_batch(bad)
miss = [x for x in bad if x not in got]
print(f"  成功 {len(got)}/{len(bad)}，缺失: {miss}")
for k in sorted(got)[:6]:
    print(f"   {k} -> {got[k]}")

print("\n=== 一次性批量拉全部 29（复现 tick 场景）===")
import core.prices as CP
CP._price_cache.clear()
got2 = fetch_prices_batch(bad)
print(f"  批量结果 {len(got2)}/{len(bad)}")

print("\n=== fusion_center 持仓 & 复算 NAV ===")
rows = c.execute("SELECT code,name,shares,avg_cost FROM strategy_positions WHERE account_id='fusion_center' ORDER BY code").fetchall()
codes = [r[0] for r in rows]
print(f"  持仓 {len(rows)} 只")
CP._price_cache.clear()
p = fetch_prices_batch(codes)
print(f"  拉到实时价 {len(p)}/{len(codes)}; 缺失: {[x for x in codes if x not in p]}")
cash = c.execute("SELECT cash FROM strategy_accounts WHERE account_id='fusion_center' AND date='20260914'").fetchone()
print("  库内 cash:", cash)
pv = sum(r[2] * (p.get(r[0]) or r[3]) for r in rows)
print(f"  实时价市值={pv:,.0f}  复算NAV={cash[0]+pv:,.0f}")
row = c.execute("SELECT date,nav,cash,pos_value,daily_ret,n_pos,created_at FROM strategy_accounts WHERE account_id='fusion_center' ORDER BY date DESC LIMIT 2").fetchall()
for r in row:
    print("  库内:", r)

print("\n=== 各活跃账户最新行（含 created_at）===")
for r in c.execute("""SELECT s.account_id,s.date,s.nav,s.daily_ret,s.created_at FROM strategy_accounts s
  JOIN (SELECT account_id,MAX(date) md FROM strategy_accounts GROUP BY account_id) m
  ON s.account_id=m.account_id AND s.date=m.md ORDER BY s.account_id"""):
    print("  ", r)
c.close()
