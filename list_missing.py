#!/usr/bin/env python3
from core import db

conn_tushare = db.get_tushare_db()
conn_state = db._safe_connect('state.db', read_only=True)

# 获取所有股票
all_stocks = conn_tushare.execute("""
    SELECT ts_code, name FROM stock_basic WHERE delist_date IS NULL ORDER BY ts_code
""").fetchall()

# 已写入的股票
written = set(r[0].split('.')[0] for r in conn_state.execute(
    "SELECT DISTINCT stock_code FROM signal_history WHERE date='2026-07-22'"
).fetchall())

# 缺失的股票
print("缺失的 34 只股票:")
print("-" * 70)
for ts_code, name in all_stocks:
    code = ts_code.split('.')[0]
    if code not in written:
        # 检查 K 线数量
        n = conn_tushare.execute(
            "SELECT COUNT(*), MIN(date), MAX(date) FROM stock_daily WHERE stock_code=?",
            [code]
        ).fetchone()
        print(f"{ts_code} {name[:12]:12s} K 线:{n[0]:5d}条 ({n[1]}~{n[2]})")

conn_tushare.close()
conn_state.close()
