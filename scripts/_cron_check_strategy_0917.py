#!/usr/bin/env python3
import sqlite3, os
SB = os.path.expanduser("~/.hermes/stockdb")
today = "20260917"
c = sqlite3.connect(os.path.join(SB, "ledger.db"))

print("=== A. ca_run_log 今日 ===")
try:
    for r in c.execute("SELECT * FROM ca_run_log ORDER BY rowid DESC LIMIT 8"):
        print("  ", str(r)[:300])
except Exception as e:
    print("  err", e)

print("\n=== B. 今日各账户 strategy_accounts 行 ===")
for r in c.execute("SELECT account_id,date,nav,cash,pos_value,daily_ret,n_pos FROM strategy_accounts WHERE date=? ORDER BY account_id", (today,)):
    print("  ", r)

print("\n=== C. 今日 trade_log (按策略/方向汇总) ===")
for r in c.execute("""SELECT strategy,direction,COUNT(*),SUM(amount) FROM trade_log
   WHERE REPLACE(trade_date,'-','')=? GROUP BY strategy,direction""", (today,)):
    print("  ", r)

print("\n=== D. execution_logs 今日异常 (ERROR/fail) ===")
try:
    for r in c.execute("""SELECT * FROM execution_logs WHERE REPLACE(COALESCE(log_date,''),'-','')=? AND (msg LIKE '%rror%' OR msg LIKE '%ail%' OR msg LIKE '%失败%') ORDER BY rowid DESC LIMIT 10""", (today,)):
        print("  ", str(r)[:250])
except Exception as e:
    print("  err", e)

print("\n=== E. 最近3次 run_log 计数(看tick频率) ===")
try:
    for r in c.execute("SELECT COUNT(*), MAX(rowid) FROM ca_run_log"):
        print("  ", r)
except Exception as e:
    print("  err", e)
