#!/usr/bin/env python3
"""修复 stk_limit 表（旧表 schema 不对且为空，重建后从 tushare 导入）"""
import duckdb

STOCK = '/Users/zantao/.hermes/stockdb/stock.db'
TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'

conn = duckdb.connect(STOCK)
conn.execute(f"ATTACH '{TUSHARE}' AS ts (READ_ONLY)")

# Check current state
try:
    cnt = conn.execute("SELECT COUNT(*) FROM stk_limit").fetchone()[0]
    schema = conn.execute("DESCRIBE stk_limit").fetchall()
    print(f"当前 stk_limit: {cnt} 行")
    print("当前 schema:")
    for c in schema:
        print(f"  {c[0]}: {c[1]}")
except Exception as e:
    print(f"stk_limit 不存在或错误: {e}")

# Drop and recreate with correct schema
conn.execute("DROP TABLE IF EXISTS stk_limit")
print("\n重建 stk_limit 表...")
conn.execute("""
    CREATE TABLE stk_limit (
        date VARCHAR,
        stock_code VARCHAR,
        up_limit DOUBLE,
        down_limit DOUBLE
    )
""")

print("从 tushare 导入...")
conn.execute("""
    INSERT INTO stk_limit 
    (date, stock_code, up_limit, down_limit)
    SELECT 
        trade_date, SPLIT_PART(ts_code, '.', 1),
        up_limit, down_limit
    FROM ts.stk_limit
""")
conn.commit()

cnt = conn.execute("SELECT COUNT(*) FROM stk_limit").fetchone()[0]
print(f"✅ stk_limit: {cnt} 条")

conn.execute("DETACH ts")
conn.close()

print("\n=== 最终 stock.db 全表验证 ===")
stk = duckdb.connect(STOCK)
tables = stk.execute("SHOW TABLES").fetchall()
for t in tables:
    try:
        cnt = stk.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
        print(f"  {t[0]}: {cnt:,}")
    except Exception as e:
        print(f"  {t[0]}: ERROR - {e}")
stk.close()
