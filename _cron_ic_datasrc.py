#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_cron_ic_datasrc.py — 查分组IC样本骤降根因: stk_factor/daily_basic 日行数"""
import duckdb

tdb = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)

print("== stk_factor 每日行数 (最近6个交易日) ==")
for r in tdb.execute("""
    SELECT trade_date, COUNT(*) AS n FROM stk_factor
    WHERE trade_date >= '20260727' GROUP BY trade_date ORDER BY trade_date
""").fetchall():
    print(f"  {r[0]}: {r[1]}")

print("\n== daily_basic 每日行数 (最近6个交易日) ==")
for r in tdb.execute("""
    SELECT trade_date, COUNT(*) AS n FROM daily_basic
    WHERE trade_date >= '20260727' GROUP BY trade_date ORDER BY trade_date
""").fetchall():
    print(f"  {r[0]}: {r[1]}")

print("\n== stock_basic 总行数 ==")
print(" ", tdb.execute("SELECT COUNT(*) FROM stock_basic").fetchone()[0])

print("\n== daily 每日行数 (最近6个交易日) ==")
for r in tdb.execute("""
    SELECT trade_date, COUNT(*) AS n FROM daily
    WHERE trade_date >= '20260727' GROUP BY trade_date ORDER BY trade_date
""").fetchall():
    print(f"  {r[0]}: {r[1]}")

tdb.close()
