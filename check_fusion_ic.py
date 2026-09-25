#!/usr/bin/env python3
import sqlite3
conn = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')

# 看7/30的融合分分布（用新参数重算后的）
print('=== 7/30 fusion_3f_signals ===')
result = conn.execute("""
    SELECT 
        COUNT(*) as n,
        AVG(fusion_3f_score) as avg_score,
        MIN(fusion_3f_score) as min_score,
        AVG(CASE WHEN fusion_3f_score >= (
            SELECT fusion_3f_score FROM fusion_3f_signals
            WHERE REPLACE(date, '-', '') = '20260730'
            ORDER BY fusion_3f_score DESC LIMIT 1 OFFSET (SELECT CAST(COUNT(*) * 0.85 AS INTEGER) FROM fusion_3f_signals WHERE REPLACE(date, '-', '') = '20260730')
        ) THEN 1 ELSE 0 END) * 100 as pct_strong_buy
    FROM fusion_3f_signals
    WHERE REPLACE(date, '-', '') = '20260730'
""").fetchone()
print(f'n={result[0]}, avg={result[1]:.2f}, min={result[2]:.2f}')

# 直接查强买组
result2 = conn.execute("""
    SELECT 
        COUNT(*) as n,
        AVG(fusion_3f_score) as avg_score,
        MIN(fusion_3f_score) as min_score,
        MAX(fusion_3f_score) as max_score
    FROM fusion_3f_signals
    WHERE REPLACE(date, '-', '') = '20260730' AND signal = '强买'
""").fetchone()
print(f'强买组: n={result2[0]}, avg={result2[1]:.2f}, min={result2[2]:.2f}, max={result2[3]:.2f}')

# 对比7/31
result3 = conn.execute("""
    SELECT 
        COUNT(*) as n,
        AVG(fusion_3f_score) as avg_score,
        MIN(fusion_3f_score) as min_score,
        MAX(fusion_3f_score) as max_score
    FROM fusion_3f_signals
    WHERE REPLACE(date, '-', '') = '20260731' AND signal = '强买'
""").fetchone()
print(f'7/31强买: n={result3[0]}, avg={result3[1]:.2f}, min={result3[2]:.2f}, max={result3[3]:.2f}')

# 全市场对比
result4 = conn.execute("""
    SELECT 
        COUNT(*) as n,
        AVG(fusion_3f_score) as avg_score,
        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY fusion_3f_score) as p75
    FROM fusion_3f_signals
    WHERE REPLACE(date, '-', '') = '20260730'
""").fetchone()
print(f'7/30全市场: n={result4[0]}, avg={result4[1]:.2f}, p75={result4[2]:.2f}')

conn.close()
