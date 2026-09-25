#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""策略账户日更 14:05 tick 只读核查：新鲜度/账目自洽/今日动作/账户状态"""
import sqlite3, os, json, glob, datetime

os.chdir(os.path.expanduser("~/.hermes/stockdb"))
print("now:", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
c = sqlite3.connect("ledger.db")

print("\n=== strategy_accounts 每账户最新日期 + 自洽性 ===")
rows = c.execute("""
  SELECT s.account_id, s.date, s.nav, s.cash, s.pos_value, s.daily_ret, s.n_pos, s.created_at
  FROM strategy_accounts s
  JOIN (SELECT account_id, MAX(date) md FROM strategy_accounts GROUP BY account_id) m
    ON s.account_id=m.account_id AND s.date=m.md
  ORDER BY s.account_id""").fetchall()
for aid, d, nav, cash, pv, dr, npos, ts in rows:
    chk = "n/a" if None in (cash, pv, nav) else ("OK" if abs((cash + pv) - nav) < 1.0 else f"MISMATCH {cash+pv:,.0f} vs {nav:,.0f}")
    print(f"  {aid:14s} {d} nav={nav:>10,.0f} ret={dr} npos={npos} {chk} [{ts}]")

print("\n=== strategy_accounts_meta ===")
try:
    for r in c.execute("SELECT * FROM strategy_accounts_meta ORDER BY account_id").fetchall():
        print("  ", r)
except Exception as e:
    print("  ERR", e)

print("\n=== trade_log 近3个交易日动作 ===")
cols = [r[1] for r in c.execute("PRAGMA table_info(trade_log)").fetchall()]
dc = "trade_date" if "trade_date" in cols else cols[0]
for (d,) in c.execute("SELECT DISTINCT %s FROM trade_log ORDER BY %s DESC LIMIT 4" % (dc, dc)).fetchall():
    print(f"  [{d}] cols={cols}")
    for r in c.execute("SELECT * FROM trade_log WHERE %s=? LIMIT 40" % dc, (d,)).fetchall():
        print("     ", r)

print("\n=== strategy_positions 汇总 ===")
try:
    for r in c.execute("SELECT account_id, COUNT(*), SUM(shares) FROM strategy_positions GROUP BY account_id ORDER BY account_id").fetchall():
        print("  ", r)
except Exception as e:
    print("  ERR", e)

print("\n=== sim_accounts/*.json 状态 ===")
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
    last = nh[-1] if nh else {}
    print(f"  {b:26s} mtime={datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime('%m-%d %H:%M')} "
          f"closed={d.get('closed')} manual={d.get('manual')} nav={d.get('nav')} "
          f"last_nav={last.get('date')} n_pos={len(d.get('positions') or [])}")

print("\n=== 本任务 cron 最近执行 ===")
for dbn, name in ((os.path.expanduser("~/.hermes/cron/executions.db"), "executions.db"),
                  (os.path.expanduser("~/.hermes/cron/jobs.db"), "jobs.db")):
    if not os.path.exists(dbn):
        print("  missing", dbn); continue
    con = sqlite3.connect(dbn)
    tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print(f"  -- {name} tables={tabs}")
    for t in tabs:
        cols = [r[1] for r in con.execute("PRAGMA table_info(%s)" % t)]
        if "error" in cols or "job_id" in cols or "status" in cols:
            try:
                for r in con.execute("SELECT * FROM %s ORDER BY rowid DESC LIMIT 10" % t):
                    print("     ", r)
            except Exception as e:
                print("     ERR", e)
    con.close()
c.close()
