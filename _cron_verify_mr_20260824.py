"""验证 mean_reversion_strategy.py 运行结果（cron 2026-08-24）"""
import sqlite3
import duckdb
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
sdb = sqlite3.connect(str(BASE / 'state.db'))
tdx = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)

# 1. mean_reversion_signals 今日写入
print("== mean_reversion_signals 最近写入 ==")
rows = sdb.execute(
    "SELECT date, stock_code, total_score FROM mean_reversion_signals "
    "ORDER BY REPLACE(date,'-','') DESC LIMIT 3"
).fetchall()
for r in rows:
    print(f"  date={r[0]} code={r[1]} score={r[2]}")

# 2. 数据新鲜度（本次判断依据）
print("\n== 数据新鲜度 ==")
d = tdx.execute("SELECT MAX(trade_date) FROM index_daily_raw WHERE ts_code='000001.SH'").fetchone()[0]
print(f"  index_daily_raw 000001.SH 最新: {d}")
d2 = tdx.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
print(f"  daily 最新: {d2}")
nf = sdb.execute("SELECT MAX(REPLACE(date,'-','')) FROM new_factors").fetchone()[0]
print(f"  new_factors 最新: {nf}")

# 3. 上证最近 MA20 斜率复核（近 45 个交易日）
closes = [float(r[0]) for r in tdx.execute(
    "SELECT close FROM index_daily_raw WHERE ts_code='000001.SH' "
    "ORDER BY trade_date DESC LIMIT 45").fetchall()][::-1]
if len(closes) >= 40:
    ma20 = sum(closes[-20:]) / 20
    ma20_prev = sum(closes[-40:-20]) / 20
    slope = (ma20 - ma20_prev) / ma20_prev * 100
    print(f"\n== MA20 斜率复核 ==")
    print(f"  最新收盘: {closes[-1]:.2f}  MA20={ma20:.2f}  MA20_prev={ma20_prev:.2f}  斜率={slope:.2f}%")
    print(f"  近5日收盘: {[round(c,2) for c in closes[-5:]]}")

sdb.close()
tdx.close()
print("\nOK")
