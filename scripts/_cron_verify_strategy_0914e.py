#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略账户日更监督核查 20260914（只读）：NAV写入/账目自洽/持仓与账本一致性"""
import sqlite3, os, json, glob, datetime

os.chdir(os.path.expanduser("~/.hermes/stockdb"))
print("now:", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
c = sqlite3.connect("ledger.db")

print("\n=== strategy_accounts 最近6个日期 × 账户 ===")
for (d,) in c.execute("SELECT DISTINCT date FROM strategy_accounts ORDER BY date DESC LIMIT 6").fetchall():
    rows = c.execute("SELECT account_id, nav, cash, pos_value, daily_ret, n_pos, created_at "
                     "FROM strategy_accounts WHERE date=? ORDER BY account_id", (d,)).fetchall()
    print(f"[{d}]")
    for r in rows:
        aid, nav, cash, pv, dr, npos, ts = r
        chk = "" if (cash is None or pv is None or nav is None) else (
            "OK" if abs((cash + pv) - nav) < 1.0 else f"MISMATCH {cash+pv:.0f}vs{nav:.0f}")
        print(f"   {aid:14s} nav={nav:>10,.0f} cash={cash:>10,.0f} pos={pv:>10,.0f} ret={dr} npos={npos} {chk} [{ts}]")

print("\n=== meta（closed/manual 配置落库）===")
for r in c.execute("SELECT account_id,name,initial_capital,updated_at FROM strategy_accounts_meta ORDER BY account_id").fetchall():
    print("  ", r)

print("\n=== 今日(20260914)账本流水 trade_log ===")
cols = [r[1] for r in c.execute("PRAGMA table_info(trade_log)").fetchall()]
print("   cols:", cols)
dc = "trade_date" if "trade_date" in cols else ("date" if "date" in cols else cols[0])
q = f"SELECT * FROM trade_log WHERE REPLACE(CAST({dc} AS VARCHAR),'-','')='20260914'"
rows = c.execute(q).fetchall()
print(f"   rows={len(rows)}")
for r in rows[:60]:
    print("   ", r)

print("\n=== strategy_positions 按账户 ===")
for r in c.execute("SELECT account_id, COUNT(*), SUM(shares) FROM strategy_positions GROUP BY account_id ORDER BY account_id").fetchall():
    print("  ", r)

print("\n=== agent_auto 持仓明细 ===")
try:
    cols = [r[1] for r in c.execute("PRAGMA table_info(strategy_positions)").fetchall()]
    print("   cols:", cols)
    for r in c.execute("SELECT * FROM strategy_positions WHERE account_id='agent_auto'").fetchall():
        print("   ", r)
except Exception as e:
    print("   ERR", e)

print("\n=== sim_accounts JSON 状态 ===")
SA = os.path.expanduser("~/.hermes/stockdb/sim_accounts")
for p in sorted(glob.glob(os.path.join(SA, "*.json"))):
    b = os.path.basename(p)
    if ".old_" in b or ".err." in b or b.startswith("_"):
        continue
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print(f"   {b}: LOAD_ERR {e}")
        continue
    nh = d.get("nav_history") or []
    last = nh[-1] if nh else {}
    print(f"   {b:30s} closed={d.get('closed')} manual={d.get('manual')} cash={d.get('cash')} "
          f"nav={d.get('nav')} last_nav={last.get('date')} n_hist={len(nh)} n_pos={len(d.get('positions') or [])}")
c.close()
