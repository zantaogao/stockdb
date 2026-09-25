#!/usr/bin/env python3
import duckdb
conn = duckdb.connect('tushare.db', read_only=True)

print("=== stock_basic 688268-688282 ===")
rows = conn.execute("""
    SELECT ts_code, name, industry, market, list_date FROM stock_basic
    WHERE ts_code >= '688268.SH' AND ts_code <= '688282.SH' ORDER BY ts_code
""").fetchall()
for r in rows:
    print(f"  {r[0]} {r[1]} 行业={r[2]} 市场={r[3]} 上市={r[4]}")

print("\n=== daily 是否有 688270/688269 ===")
for c in ['688269.SH', '688270.SH']:
    n = conn.execute("SELECT COUNT(*) FROM daily WHERE ts_code=?", (c,)).fetchone()[0]
    print(f"  {c}: daily 行数={n}")

# 检查 6882xx 全段
print("\n=== stock_basic 全部 6882xx ===")
rows = conn.execute("""
    SELECT ts_code, name, list_date FROM stock_basic
    WHERE ts_code LIKE '6882%' ORDER BY ts_code
""").fetchall()
codes = [r[0] for r in rows]
print(f"  共 {len(codes)} 只: {codes}")

conn.close()
