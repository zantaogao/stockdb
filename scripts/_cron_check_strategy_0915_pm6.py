#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cron 监督 09-15：账户维度落库明细 + 当日成交 + 运行日志"""
import sqlite3, os

LEDGER = os.path.expanduser('~/.hermes/stockdb/ledger.db')
c = sqlite3.connect(f'file:{LEDGER}?mode=ro', uri=True)
c.row_factory = sqlite3.Row

def show(sql, label, args=()):
    print(f"\n=== {label} ===")
    try:
        for r in c.execute(sql, args):
            print("  " + " | ".join(f"{k}={r[k]}" for k in r.keys()))
    except Exception as e:
        print("  ERR", e)

show("SELECT * FROM strategy_accounts_meta ORDER BY updated_at DESC", "strategy_accounts_meta")
show("SELECT * FROM ca_run_log ORDER BY rowid DESC LIMIT 10", "ca_run_log (最近10)")
show("SELECT trade_date, account, ts_code, action, shares, price FROM trade_log WHERE REPLACE(trade_date,'-','')='20260915' ORDER BY rowid", "今日 trade_log 20260915")
show("SELECT account, COUNT(*) n, MIN(updated_at) mn, MAX(updated_at) mx FROM strategy_positions GROUP BY account ORDER BY mx DESC", "strategy_positions 按账户")
show("SELECT * FROM ca_adjustments ORDER BY rowid DESC LIMIT 10", "ca_adjustments")
show("SELECT * FROM strategy_crash_state", "strategy_crash_state")
