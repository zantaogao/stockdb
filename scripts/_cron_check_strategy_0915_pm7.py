#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cron 监督 09-15：成交/持仓表结构 + 今日明细"""
import sqlite3, os, datetime

LEDGER = os.path.expanduser('~/.hermes/stockdb/ledger.db')
c = sqlite3.connect(f'file:{LEDGER}?mode=ro', uri=True)
c.row_factory = sqlite3.Row
print("NOW:", datetime.datetime.now().isoformat())

for t in ('trade_log', 'strategy_positions', 'strategy_accounts_legacy'):
    print(f"\n-- {t} cols:", [r[1] for r in c.execute(f"PRAGMA table_info({t})")])

print("\n=== trade_log 今日 (REPLACE date 20260915) ===")
for r in c.execute("SELECT * FROM trade_log WHERE REPLACE(trade_date,'-','')='20260915' ORDER BY rowid"):
    print("  " + " | ".join(f"{k}={r[k]}" for k in r.keys()))

print("\n=== strategy_positions 按账户最新 ===")
cols = [r[1] for r in c.execute("PRAGMA table_info(strategy_positions)")]
key = 'account_id' if 'account_id' in cols else cols[0]
for r in c.execute(f"SELECT {key} a, COUNT(*) n, MAX(updated_at) mx FROM strategy_positions GROUP BY 1 ORDER BY 3 DESC"):
    print(f"  {r['a']:16s} n={r['n']:3d} last={r['mx']}")

print("\n=== strategy_accounts_legacy 20260915 ===")
for r in c.execute("SELECT * FROM strategy_accounts_legacy WHERE date='20260915'"):
    print("  " + " | ".join(f"{k}={r[k]}" for k in r.keys()))
