#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""09-14 14:46 tick 策略账户日更监督：只读核查"""
import sqlite3, os, json, glob, datetime, collections

os.chdir(os.path.expanduser("~/.hermes/stockdb"))
print("now:", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
c = sqlite3.connect("ledger.db")

print("\n=== 每账户最新一行 strategy_accounts ===")
rows = c.execute("""
  SELECT s.account_id, s.date, s.nav, s.cash, s.pos_value, s.daily_ret, s.n_pos, s.created_at
  FROM strategy_accounts s
  JOIN (SELECT account_id, MAX(date) md FROM strategy_accounts GROUP BY account_id) m
    ON s.account_id=m.account_id AND s.date=m.md
  ORDER BY s.account_id""").fetchall()
for aid, d, nav, cash, pv, dr, npos, ts in rows:
    chk = "n/a" if None in (cash, pv, nav) else ("OK" if abs((cash + pv) - nav) < 1.0 else f"MISMATCH {cash+pv:,.0f} vs {nav:,.0f}")
    print(f"  {aid:14s} {d} nav={nav:>10,.0f} ret={dr} npos={npos} {chk} [{ts}]")

print("\n=== 20260914 行数（重复检查）===")
for r in c.execute("SELECT account_id, COUNT(*) FROM strategy_accounts WHERE date='20260914' GROUP BY account_id").fetchall():
    print("  ", r)

print("\n=== meta ===")
try:
    for r in c.execute("SELECT * FROM strategy_accounts_meta ORDER BY account_id").fetchall():
        print("  ", r)
except Exception as e:
    print("  ERR", e)

print("\n=== trade_log 近8个交易日计数 ===")
for r in c.execute("SELECT REPLACE(CAST(trade_date AS VARCHAR),'-','') d, COUNT(*), SUM(direction='BUY'), SUM(direction='SELL') FROM trade_log GROUP BY d ORDER BY d DESC LIMIT 8"):
    print("  ", r)

print("\n=== 今日(20260914)全部成交 ===")
for r in c.execute("SELECT id,strategy,direction,code,name,price,quantity,amount,trade_time,notes FROM trade_log WHERE REPLACE(CAST(trade_date AS VARCHAR),'-','')='20260914' ORDER BY id"):
    print("  ", r)

print("\n=== strategy_positions 每账户 ===")
for r in c.execute("SELECT account_id, COUNT(*), ROUND(SUM(total_cost),0) FROM strategy_positions GROUP BY account_id ORDER BY account_id"):
    print("  ", r)

print("\n=== sim_accounts JSON 概览 ===")
for p in sorted(glob.glob("sim_accounts/*.json")):
    b = os.path.basename(p)
    if b.startswith("_") or ".old_" in b or ".err." in b:
        continue
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print(f"  {b:26s} LOAD_ERR {e}")
        continue
    nh = d.get("nav_history") or []
    last = str(nh[-1].get("date")) if nh else "NONE"
    tr = d.get("trades") or []
    today = [t for t in tr if str(t.get("date") or t.get("trade_date") or "").replace("-", "").startswith("20260914")]
    print(f"  {b:26s} closed={d.get('closed')} manual={d.get('manual')} nav={d.get('nav')} last_nav={last} nhist={len(nh)} npos={len(d.get('positions') or [])} trades={len(tr)} today={len(today)} mtime={datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime('%m-%d %H:%M')}")
c.close()
