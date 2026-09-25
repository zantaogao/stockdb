#!/usr/bin/env python3
import sqlite3, duckdb, os, json, glob, datetime, subprocess
SB = os.path.expanduser("~/.hermes/stockdb")
today = "20260915"

print("=== A. ca_run_log 今日 ===")
c = sqlite3.connect(os.path.join(SB, "ledger.db"))
try:
    cols = [r[1] for r in c.execute("PRAGMA table_info(ca_run_log)")]
    print("  cols:", cols)
    for r in c.execute("SELECT * FROM ca_run_log ORDER BY rowid DESC LIMIT 5"):
        print("  ", r)
except Exception as e:
    print("  err", e)

print("\n=== B. execution_logs 今日 (非main) ===")
try:
    for r in c.execute("SELECT * FROM execution_logs WHERE REPLACE(COALESCE(log_date,''),'-','')=? ORDER BY rowid DESC LIMIT 10", (today,)):
        print("  ", str(r)[:200])
except Exception as e:
    print("  err", e)

print("\n=== C. 中证1000 最近5日 ===")
try:
    con = duckdb.connect(os.path.join(SB, "tushare.db"), read_only=True)
    for r in con.execute("SELECT trade_date, close, pct_chg FROM index_daily WHERE ts_code='000852.SH' ORDER BY trade_date DESC LIMIT 5").fetchall():
        print("  ", r)
except Exception as e:
    print("  err", e)

print("\n=== D. strategy_accounts 今日全部行 ===")
for r in c.execute("SELECT account_id,date,nav,cash,pos_value,daily_ret,n_pos FROM strategy_accounts WHERE date=?", (today,)):
    print("  ", r)

print("\n=== E. cmmr 今日买入是否超预算 (target=62,411) ===")
rows = c.execute("""SELECT code, SUM(quantity), SUM(amount) FROM trade_log
   WHERE REPLACE(trade_date,'-','')=? AND strategy='cmmr' AND direction='BUY' GROUP BY code""", (today,)).fetchall()
for r in rows: print("  ", r)

print("\n=== F. 持仓数 vs 目标仓数 (等权) ===")
for acc in ("cmmr","cmmr_fusion","fusion_center","center_dual","agent_auto"):
    nav, cash = c.execute("SELECT nav, cash FROM strategy_accounts WHERE account_id=? ORDER BY date DESC LIMIT 1", (acc,)).fetchone()
    n = c.execute("SELECT COUNT(*) FROM strategy_positions WHERE account_id=?", (acc,)).fetchone()[0]
    print(f"  {acc:14s} nav={nav:,.0f} cash={cash:,.0f} 持仓={n} 单仓目标≈{(nav-cash)/n if n else 0:,.0f}")
