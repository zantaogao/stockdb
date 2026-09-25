#!/usr/bin/env python3
"""Final check: ETF chain real data in tushare.db."""
import duckdb, datetime

conn = duckdb.connect("/Users/zantao/.hermes/stockdb/tushare.db", read_only=True)

fb = conn.execute("SELECT count(*) FROM fund_basic").fetchone()[0]
fd = conn.execute("SELECT count(*) FROM fund_daily").fetchone()[0]
mx = conn.execute("SELECT MAX(trade_date) FROM fund_daily").fetchone()[0]
print(f"fund_basic: {fb} | fund_daily: {fd:,} rows | MAX(trade_date): {mx}")

if mx:
    dt = datetime.datetime.strptime(str(mx), "%Y%m%d")
    delta = (datetime.datetime.now() - dt).days
    print(f"fund_daily 最新 {mx} = {delta} 天前 (今天 {datetime.date.today()})")

# 抽查最近几天有多少只ETF有净值
recent = conn.execute(
    "SELECT trade_date, count(*) FROM fund_daily WHERE trade_date >= '20260725' GROUP BY trade_date ORDER BY trade_date DESC"
).fetchall()
for r in recent:
    print(" ", r)
conn.close()
