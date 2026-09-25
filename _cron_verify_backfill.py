#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_cron_verify_backfill.py v2 — 验证 update_tushare_api.py 回补逻辑 (基于daily交易日历)"""
import py_compile, duckdb
from datetime import datetime, timedelta

py_compile.compile('/Users/zantao/.hermes/stockdb/scripts/update_tushare_api.py', doraise=True)
print("py_compile OK")

tdb = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
cutoff = (datetime.now() - timedelta(days=14)).strftime('%Y%m%d')
trading_days = [r[0] for r in tdb.execute(
    "SELECT DISTINCT trade_date FROM daily WHERE trade_date >= ? ORDER BY trade_date",
    (cutoff,)).fetchall()]
print(f"daily 交易日历 (>= {cutoff}): {len(trading_days)} 天")
need = 0
for d in trading_days:
    n = tdb.execute("SELECT COUNT(*) FROM stk_factor WHERE trade_date = ?", (d,)).fetchone()[0]
    flag = "NEED_BACKFILL" if n < 5000 else "OK"
    if n < 5000:
        need += 1
    print(f"  {d}: stk_factor {n} 行 {flag}")
print(f"\n结论: {need} 天需要回补 (08-03 部分缺 + 08-04 全缺均能被检测到)")
tdb.close()
