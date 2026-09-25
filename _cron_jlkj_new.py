#!/usr/bin/env python3
import duckdb
conn = duckdb.connect('tushare.db', read_only=True)

# 最新上市的股票（2026年）
print("=== 2026年上市股票 ===")
rows = conn.execute("""
    SELECT ts_code, name, industry, market, list_date
    FROM stock_basic WHERE list_date >= '20260101'
    ORDER BY list_date DESC LIMIT 40
""").fetchall()
for r in rows:
    print(f"  {r[0]} {r[1]} 行业={r[2]} 市场={r[3]} 上市={r[4]}")

print(f"\nstock_basic 总数: {conn.execute('SELECT COUNT(*) FROM stock_basic').fetchone()[0]}")

# daily 里 6882xx 段最新有数据的
print("\n=== daily 6882xx 最近有交易的 ===")
rows = conn.execute("""
    SELECT ts_code, MAX(trade_date) FROM daily
    WHERE ts_code LIKE '6882%' GROUP BY ts_code ORDER BY 2 DESC LIMIT 15
""").fetchall()
for r in rows:
    print(f"  {r[0]} 最新交易={r[1]}")

conn.close()
