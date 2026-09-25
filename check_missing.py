#!/usr/bin/env python3
from core import db

conn_tushare = db.get_tushare_db()
conn_state = db._safe_connect('state.db', read_only=True)

# 从 tushare.db 获取所有股票
all_stocks = conn_tushare.execute("""
    SELECT ts_code FROM stock_basic WHERE delist_date IS NULL
""").fetchall()
all_codes = set(c[0].split('.')[0] for c in all_stocks)
print(f"tushare.db 股票：{len(all_codes)}只")

# 已写入的股票
written = conn_state.execute("""
    SELECT DISTINCT stock_code FROM signal_history WHERE date='2026-07-22'
""").fetchall()
written_codes = set(c[0] for c in written)
print(f"已写入：{len(written_codes)}只")

# 缺失
missing = all_codes - written_codes
print(f"缺失：{len(missing)}只")
print(f"已写入但不在 tushare.db: {len(written_codes - all_codes)}只")
print(f"在 tushare.db 但未写入：{len(missing)}只")

# 检查缺失的股票为什么没有 K 线
print(f"\n缺失股票分析:")
for code in sorted(list(missing))[:20]:
    count = conn_tushare.execute(
        "SELECT COUNT(*), MIN(date), MAX(date) FROM stock_daily WHERE stock_code=?",
        [code]
    ).fetchone()
    print(f"  {code}: {count[0]}条 K 线 ({count[1]}~{count[2]})")

conn_tushare.close()
conn_state.close()
