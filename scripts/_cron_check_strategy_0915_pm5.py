#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cron 监督：检查 strategy_accounts_daily.sh 本 tick 是否正常落库（09-15 盘后）"""
import sqlite3, os, datetime

LEDGER = os.path.expanduser('~/.hermes/stockdb/ledger.db')
c = sqlite3.connect(f'file:{LEDGER}?mode=ro', uri=True)
tabs = [r[0] for r in c.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1")]
print("LEDGER TABLES:")
for t in tabs:
    try:
        n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:32s} rows={n}")
    except Exception as e:
        print(f"  {t:32s} ERR {e}")

def cols(t):
    return [r[1] for r in c.execute(f"PRAGMA table_info({t})")]

print("\n=== 各策略账户最新日期 ===")
for t in tabs:
    cl = cols(t)
    datecol = None
    for cand in ('date', 'trade_date', 'snapshot_date', 'updated_at', 'trade_time', 'create_time'):
        if cand in cl:
            datecol = cand
            break
    if datecol is None:
        continue
    try:
        rows = c.execute(
            f"SELECT {datecol}, COUNT(*) FROM {t} GROUP BY 1 ORDER BY 1 DESC LIMIT 6"
        ).fetchall()
        print(f"  {t} [{datecol}]: {rows}")
    except Exception as e:
        print(f"  {t}: ERR {e}")
