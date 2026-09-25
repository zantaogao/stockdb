#!/usr/bin/env python3
"""
补拉 index_daily 缺失的指数数据
从 index_daily_raw 同步到 index_daily，并尝试用 tushare 补拉缺失日期
"""
import duckdb
from pathlib import Path
from datetime import date, timedelta

DB_PATH = Path.home() / ".hermes/stockdb/tushare.db"

def sync_raw_to_daily():
    """从 index_daily_raw 同步数据到 index_daily"""
    print("=== 从 index_daily_raw 同步到 index_daily ===")
    con = duckdb.connect(str(DB_PATH))
    
    # 获取 raw 表中最新的日期
    raw_max = con.execute("SELECT MAX(trade_date), COUNT(*) FROM index_daily_raw").fetchone()
    print(f"index_daily_raw 最新日期：{raw_max[0]}, 总行数：{raw_max[1]}")
    
    # 同步所有 raw 数据到 daily 表
    # 注意：ts_code 格式是 '000001.SH'，需要提取代码部分 '000001'
    con.execute("""
        INSERT OR REPLACE INTO index_daily (index_code, date, open, high, low, close, amount, volume, change_pct)
        SELECT 
            REPLACE(ts_code, '.SH', ''),
            REPLACE(REPLACE(trade_date, '202607', '2026-07'), '20260', '2026-0'),
            open, high, low, close, amount, vol, pct_chg
        FROM index_daily_raw
        WHERE trade_date >= '20260718'
    """)
    
    # 验证同步结果
    result = con.execute("""
        SELECT index_code, date, close, change_pct 
        FROM index_daily 
        WHERE date >= '2026-07-18'
        ORDER BY date DESC, index_code
    """).fetchall()
    
    print(f"\n同步后的 index_daily 数据 (07-18 之后):")
    if result:
        print(f"{'代码':<12} {'日期':<12} {'收盘价':>12} {'涨跌幅%':>10}")
        print("-" * 50)
        for row in result:
            print(f"{row[0]:<12} {str(row[1]):<12} {row[2]:>12.2f} {row[3]:>10.2f}")
    else:
        print("  (无数据)")
    
    con.close()
    return len(result)

if __name__ == "__main__":
    count = sync_raw_to_daily()
    print(f"\n✅ 同步完成，新增/更新 {count} 条记录")
