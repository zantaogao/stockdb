#!/usr/bin/env python3
"""cron 巡检 2026-09-15: 今日策略账户流水 + 各账户持仓数/现金"""
import sqlite3
DB = '/Users/zantao/.hermes/stockdb/ledger.db'
db = sqlite3.connect(DB); db.row_factory = sqlite3.Row

print("== trade_log 2026-09-14 起 ==")
for r in db.execute("""SELECT trade_date, trade_time, strategy, code, name, direction, price, quantity, amount, notes
                       FROM trade_log WHERE REPLACE(trade_date,'-','') >= '20260914'
                       ORDER BY trade_date, trade_time"""):
    d = dict(r)
    print(f"  {d['trade_date']} {d['trade_time']} [{d['strategy']}] {d['direction']:4s} {d['code']} {d['name']} {d['quantity']}@{d['price']} = {d['amount']} | {d['notes']}")

print("\n== 今日各策略账户成交笔数 ==")
for r in db.execute("""SELECT strategy, direction, COUNT(*) n, SUM(amount) amt FROM trade_log
                       WHERE REPLACE(trade_date,'-','')='20260915' GROUP BY strategy, direction"""):
    print("  ", dict(r))

print("\n== 各账户持仓概览 (今天) ==")
for r in db.execute("""SELECT account_id, COUNT(*) n, SUM(shares*avg_cost) cost FROM strategy_positions GROUP BY account_id ORDER BY account_id"""):
    print("  ", dict(r))

print("\n== strategy_crash_state ==")
cols = [c[1] for c in db.execute("PRAGMA table_info(strategy_crash_state)")]
print(" cols:", cols)
for r in db.execute("SELECT * FROM strategy_crash_state ORDER BY rowid DESC LIMIT 10"):
    print("  ", dict(r))
db.close()
