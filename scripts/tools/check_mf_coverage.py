#!/usr/bin/env python3
"""检查money_flow缺失情况，制定补全计划"""
import duckdb, os
from datetime import date

DB = os.path.expanduser('~/.hermes/stockdb/stock.db')
conn = duckdb.connect(DB)

# 1. 现有数据概况
r = conn.execute("""
    SELECT COUNT(DISTINCT date) as total_dates,
           COUNT(DISTINCT stock_code) as total_stocks,
           COUNT(*) as total_rows,
           MIN(date) as first_date,
           MAX(date) as last_date
    FROM money_flow
""").fetchone()
print(f"money_flow 现有: {r[3]} ~ {r[4]}, {r[0]}个交易日, {r[1]}只股票, {r[2]}行")

# 2. 按年统计
for y in range(2025, 2027):
    r2 = conn.execute(f"""
        SELECT COUNT(DISTINCT date), COUNT(*), 
               (SELECT COUNT(DISTINCT date) FROM stock_daily WHERE date BETWEEN '{y}-01-01' AND '{y}-12-31')
        FROM money_flow WHERE date BETWEEN '{y}-01-01' AND '{y}-12-31'
    """).fetchone()
    print(f"{y}: {r2[0]}/{r2[2]} 个交易日有数据, {r2[1]}行")

# 3. 2025年每个月的覆盖情况
print("\n月度覆盖:")
for m in range(1, 13):
    sd = conn.execute(f"""
        SELECT COUNT(DISTINCT date) FROM stock_daily 
        WHERE date BETWEEN '2025-{m:02d}-01' AND '2025-{m:02d}-31'
    """).fetchone()[0]
    mf = conn.execute(f"""
        SELECT COUNT(DISTINCT date) FROM money_flow 
        WHERE date BETWEEN '2025-{m:02d}-01' AND '2025-{m:02d}-31'
    """).fetchone()[0]
    if sd > 0:
        print(f"  2025-{m:02d}: MF={mf}天 / 交易日={sd}天")

# 4. 检查平均每只股票有多少条记录
r3 = conn.execute("""
    SELECT AVG(cnt) FROM (
        SELECT stock_code, COUNT(*) as cnt FROM money_flow GROUP BY stock_code
    )
""").fetchone()[0]
print(f"\n每只股票平均 {r3:.0f} 条记录")

# 5. 如果每只股票从AKShare能拉到120条(6个月)
# 2025-11到2026-05共约 120个交易日
print(f"\n如果每只股票从AKShare拉120条:")
print(f"  总数据量: ~120条 × 5200只 = 624,000行 (去重后)")
print(f"  现有: {r[2]}行")
print(f"  可补充: ~{624000 - r[2]}行 (含已有日期的补缺)")

# 6. 估算AKShare单个股票耗时
print(f"\nAKShare拉取耗时估算:")
print(f"  单只股票: ~2秒(含网络)")
print(f"  5200只串行: ~{5200*2/3600:.1f}小时")
print(f"  如果并行20路: ~{5200*2/20/60:.0f}分钟")
