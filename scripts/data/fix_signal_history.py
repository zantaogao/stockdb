#!/usr/bin/env python3
"""修复 signal_history 表结构（增加字段支持完整的评分记录）"""
import duckdb

STOCK = '/Users/zantao/.hermes/stockdb/stock.db'

conn = duckdb.connect(STOCK)

# 检查当前 schema
existing = conn.execute("""
    SELECT table_name FROM information_schema.tables
    WHERE table_schema='main' AND table_name='signal_history'
""").fetchone()

if existing:
    print("删除旧的 signal_history 表")
    conn.execute("DROP TABLE signal_history")

print("重建 signal_history 表...")
conn.execute("""
    CREATE TABLE signal_history (
        date VARCHAR NOT NULL,
        stock_code VARCHAR NOT NULL,
        stock_name VARCHAR,
        industry VARCHAR,
        fusion_score DOUBLE,
        reg20 DOUBLE,
        reg40 DOUBLE,
        reg10 DOUBLE,
        gtja_score DOUBLE,
        deviation120 DOUBLE,
        final_score DOUBLE,
        fusion_avg DOUBLE,
        cls27_prob DOUBLE,
        lstm DOUBLE,
        reg_pred DOUBLE,
        reg10_pred DOUBLE,
        reg40_pred DOUBLE,
        created_at VARCHAR,
        PRIMARY KEY (date, stock_code)
    )
""")

conn.execute("""
    CREATE INDEX idx_signal_date ON signal_history(date)
""")
conn.execute("""
    CREATE INDEX idx_signal_code ON signal_history(stock_code)
""")
conn.execute("""
    CREATE INDEX idx_signal_score ON signal_history(final_score DESC)
""")

conn.commit()

# 验证
count = conn.execute("SELECT COUNT(*) FROM signal_history").fetchone()[0]
print(f"✅ signal_history 表已重建，当前 {count} 条")

conn.close()
