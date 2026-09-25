#!/usr/bin/env python3
"""09-07 收尸：把看门狗杀掉前已写好数据的 tushare.db.new 交换成活库。
流程: 写锁 → CHECKPOINT(合WAL) → 关键表校验 → os.replace → 只读复验。
校验不过就保持原样不动。"""
import os, sys, duckdb
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.db_lock import tushare_write_lock

NEW = '/Users/zantao/.hermes/stockdb/tushare.db.new'
LIVE = '/Users/zantao/.hermes/stockdb/tushare.db'

with tushare_write_lock(timeout=60):
    con = duckdb.connect(NEW, read_only=False)
    con.execute("CHECKPOINT")
    print("CHECKPOINT 完成")
    checks = {
        'daily':        "select max(trade_date), count(*) filter (where trade_date='20260907') from daily",
        'daily_basic':  "select max(trade_date), count(*) filter (where trade_date='20260907') from daily_basic",
        'adj_factor':   "select max(trade_date), count(*) filter (where trade_date='20260907') from adj_factor",
        'index_daily':  "select max(date) from index_daily",
        'fin_income':   "select max(end_date) from fin_income",
    }
    ok = True
    for t, q in checks.items():
        row = con.execute(q).fetchone()
        print(' ', t, row)
        if t in ('daily', 'daily_basic', 'adj_factor'):
            if str(row[0]) < '20260907' or (row[1] or 0) < 5000:
                ok = False; print(f'  ❌ {t} 不达标，放弃交换')
    ntab = con.execute("select count(*) from information_schema.tables where table_schema='main' and table_type='BASE TABLE'").fetchone()[0]
    print('  表数:', ntab, '(期望>=12)')
    if ntab < 12: ok = False
    con.close()
    if not ok:
        sys.exit(1)
    os.replace(NEW, LIVE)
    print('os.replace 完成')

# 只读复验
vc = duckdb.connect(LIVE, read_only=True)
for q in ("select max(trade_date) from daily",
          "select count(*) from daily where trade_date='20260907'",
          "select max(trade_date) from daily_basic",
          "select max(trade_date) from stk_limit"):
    print('  复验:', q, '->', vc.execute(q).fetchone()[0])
vc.close()
print('SWAP_DONE')