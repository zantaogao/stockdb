"""
板块共振分析
============
研究涨停集中在什么行业时次日溢价最高，以及"板块效应"对打板成功率的影响。

核心假设: 当某行业出现多只涨停股时，该行业的次日溢价率更高。
"""

import duckdb
import os
from collections import defaultdict

DB_PATH = os.path.expanduser('~/.hermes/stockdb/tushare.db')

def safe_connect():
    try:
        return duckdb.connect(str(DB_PATH), read_only=True)
    except Exception:
        wal = DB_PATH + '.wal'
        if os.path.exists(wal):
            os.remove(wal)
        return duckdb.connect(str(DB_PATH), read_only=True)

# ── 分析1: 各行业涨停次日表现 ────────────────────────────────

def analyze_industry_premium():
    """各行业涨停股的T+1溢价率"""
    con = safe_connect()
    
    print("=" * 70)
    print("行业涨停溢价分析")  
    print("=" * 70)
    print("(2025年6月以来各行业涨停股次日表现)")
    
    results = con.execute("""
        WITH daily_with_next AS (
            SELECT 
                ts_code, trade_date, close, pct_chg, pre_close, open,
                LEAD(close) OVER w as next_close
            FROM daily WHERE ts_code LIKE '0%' AND trade_date >= '20250601'
            WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date ASC)
        ),
        limit_days AS (
            SELECT 
                dn.ts_code,
                dn.trade_date as limit_date,
                dn.close as limit_price,
                dn.next_close,
                ROUND(dn.pct_chg, 2) as pct_chg,
                si.industry
            FROM daily_with_next dn
            JOIN stk_limit sl ON dn.ts_code = sl.ts_code AND dn.trade_date = sl.trade_date
            LEFT JOIN stock_info si ON SUBSTR(dn.ts_code, 1, LENGTH(dn.ts_code)-3) = si.stock_code
            WHERE dn.close >= sl.up_limit * 0.98
              AND dn.next_close IS NOT NULL
        )
        SELECT 
            industry,
            COUNT(*) as cnt,
            ROUND(AVG((next_close - limit_price) / limit_price * 100), 2) as avg_t1_return,
            ROUND(100 * SUM(CASE WHEN (next_close - limit_price) > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY (next_close - limit_price) / limit_price * 100) as p75
        FROM limit_days WHERE industry IS NOT NULL AND industry != ''
        GROUP BY industry
        HAVING cnt >= 20
        ORDER BY avg_t1_return DESC, cnt DESC
    """).fetchall()
    
    print(f"\n{'行业':<8} {'样本数':>6} {'T+1均值%':>9} {'胜率%':>7} {'P75%':>7}")
    print("─" * 50)
    
    for r in results[:30]:
        bar_len = int(r[2] * 4) if r[2] > 0 else 0
        bar = '█' * min(bar_len, 30)
        print(f"{r[0]:<8} {r[1]:>6} {r[2]:>+7.2f}% "
              f"{r[3]:>5.1f}% {r[4]:>+5.1f}")

    con.close()

# ── 分析2: 板块共振效应 ─────────────────────────────────────

def analyze_sector_cluster():
    """当日同行业涨停越多，次日是否越强"""
    con = safe_connect()
    
    print("\n\n" + "=" * 70)
    print("板块共振效应分析")
    print("=" * 70)
    print("(同日同行业涨停数 vs T+1表现)")
    
    # 计算每日各行业的涨停数量，然后看该行业涨停股T+1表现
    results = con.execute("""
        WITH daily_with_next AS (
            SELECT 
                ts_code, trade_date, close, pct_chg, pre_close, open,
                LEAD(close) OVER w as next_close
            FROM daily WHERE ts_code LIKE '0%' AND trade_date >= '20250601'
            WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date ASC)
        ),
        limit_days AS (
            SELECT 
                dn.ts_code, dn.trade_date as limit_date,
                dn.close as limit_price, dn.next_close,
                si.industry
            FROM daily_with_next dn
            JOIN stk_limit sl ON dn.ts_code = sl.ts_code AND dn.trade_date = sl.trade_date
            LEFT JOIN stock_info si ON SUBSTR(dn.ts_code, 1, LENGTH(dn.ts_code)-3) = si.stock_code
            WHERE dn.close >= sl.up_limit * 0.98
              AND dn.next_close IS NOT NULL
        ),
        daily_industry_counts AS (
            SELECT 
                limit_date as dt, industry, COUNT(*) as cluster_size
            FROM limit_days WHERE industry IS NOT NULL AND industry != ''
            GROUP BY limit_date, industry
        )
        SELECT 
            CASE 
                WHEN dic.cluster_size = 1 THEN '孤立(1只)'
                WHEN dic.cluster_size <= 3 THEN '小集群(2-3只)'
                WHEN dic.cluster_size <= 5 THEN '中集群(4-5只)' 
                ELSE '大集群(6+只)'
            END as cluster_label,
            COUNT(*) as total_limit_days,
            ROUND(AVG((ld.next_close - ld.limit_price) / ld.limit_price * 100), 2) as avg_t1_return,
            ROUND(100 * SUM(CASE WHEN (ld.next_close - ld.limit_price) > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate
        FROM limit_days ld
        JOIN daily_industry_counts dic ON ld.limit_date = dic.dt AND ld.industry = dic.industry
        WHERE ld.industry IS NOT NULL AND ld.industry != ''
        GROUP BY 
            CASE 
                WHEN dic.cluster_size = 1 THEN '孤立(1只)'
                WHEN dic.cluster_size <= 3 THEN '小集群(2-3只)'
                WHEN dic.cluster_size <= 5 THEN '中集群(4-5只)' 
                ELSE '大集群(6+只)'
            END
        ORDER BY avg_t1_return DESC
    """).fetchall()
    
    print(f"\n{'集群规模':<12} {'涨停日数':>8} {'T+1均值%':>9} {'胜率%':>7}")
    print("─" * 45)
    
    for r in results:
        indicator = "★★★" if float(r[3]) > 60 else "★★" if float(r[3]) > 55 else ""
        print(f"{r[0]:<12} {r[1]:>8} {r[2]:>+7.2f}% {r[3]:>5.1f}%")

    con.close()

# ── 分析3: 板块热度轮动趋势 ──────────────────────────────────

def analyze_sector_momentum():
    """近半年各月热门行业及其表现"""
    con = safe_connect()
    
    print("\n\n" + "=" * 70)
    print("月度板块热度轮动")
    print("=" * 70)
    print("(每月涨停最集中的行业)")
    
    results = con.execute("""
        WITH daily_with_next AS (
            SELECT 
                ts_code, trade_date, close, pct_chg, pre_close, open,
                LEAD(close) OVER w as next_close
            FROM daily WHERE ts_code LIKE '0%' AND trade_date >= '20251201'
            WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date ASC)
        ),
        limit_days AS (
            SELECT 
                dn.ts_code, dn.trade_date as limit_date,
                dn.close as limit_price, dn.next_close, si.industry
            FROM daily_with_next dn
            JOIN stk_limit sl ON dn.ts_code = sl.ts_code AND dn.trade_date = sl.trade_date
            LEFT JOIN stock_info si ON SUBSTR(dn.ts_code, 1, LENGTH(dn.ts_code)-3) = si.stock_code
            WHERE dn.close >= sl.up_limit * 0.98
              AND dn.next_close IS NOT NULL
        )
        SELECT 
            SUBSTR(limit_date, 1, 6) as month,
            industry,
            COUNT(*) as cnt
        FROM limit_days WHERE industry IS NOT NULL AND industry != ''
        GROUP BY month, industry
        HAVING cnt >= 5
        ORDER BY month DESC, cnt DESC
    """).fetchall()
    
    current_month = None
    for r in results:
        if r[0] != current_month:
            current_month = r[0]
            print(f"\n{current_month}:")
        
        bar = '█' * (r[2] // 3) + str(r[2])
        print(f"  {r[1]:<8} {bar}")

    # T+1表现最好的Top行业
    print("\n\n=== T+1表现最佳的Top5行业 ===")
    
    top_industries = con.execute("""
        WITH daily_with_next AS (
            SELECT 
                ts_code, trade_date, close, pct_chg, pre_close, open,
                LEAD(close) OVER w as next_close
            FROM daily WHERE ts_code LIKE '0%' AND trade_date >= '20250601'
            WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date ASC)
        ),
        limit_days AS (
            SELECT 
                dn.ts_code, dn.trade_date as limit_date,
                dn.close as limit_price, dn.next_close, si.industry
            FROM daily_with_next dn
            JOIN stk_limit sl ON dn.ts_code = sl.ts_code AND dn.trade_date = sl.trade_date
            LEFT JOIN stock_info si ON SUBSTR(dn.ts_code, 1, LENGTH(dn.ts_code)-3) = si.stock_code
            WHERE dn.close >= sl.up_limit * 0.98
              AND dn.next_close IS NOT NULL
        )
        SELECT 
            industry, COUNT(*) as cnt,
            ROUND(AVG((next_close - limit_price) / limit_price * 100), 2) as avg_return,
            ROUND(100 * SUM(CASE WHEN (next_close - limit_price) > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate,
            ROUND(MAX((next_close - limit_price) / limit_price * 100), 2) as best_single
        FROM limit_days WHERE industry IS NOT NULL AND industry != ''
        GROUP BY industry HAVING cnt >= 30
        ORDER BY avg_return DESC LIMIT 10
    """).fetchall()
    
    print(f"\n{'行业':<8} {'样本数':>6} {'T+1均值%':>9} {'胜率%':>7}")
    print("─" * 45)
    for r in top_industries:
        print(f"{r[0]:<8} {r[1]:>6} {r[2]:>+7.2f}% {r[3]:>5.1f}%")

    con.close()

# ── 分析4: 最佳"行业+市值"组合策略 ────────────────────────────

def analyze_optimal_strategy():
    """找出涨停时T+1收益最高的筛选条件组合"""
    con = safe_connect()
    
    print("\n\n" + "=" * 70)
    print("最优打板条件组合")  
    print("=" * 70)
    print("(行业 x 市值 x 开盘方式 的交叉分析)")
    
    # 取T+1表现最好的5个行业，看它们在不同市值区间的表现
    results = con.execute("""
        WITH daily_with_next AS (
            SELECT 
                ts_code, trade_date, close, pct_chg, pre_close, open,
                LEAD(close) OVER w as next_close
            FROM daily WHERE ts_code LIKE '0%' AND trade_date >= '20250601'
            WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date ASC)
        ),
        limit_days AS (
            SELECT 
                dn.ts_code, dn.trade_date as limit_date,
                dn.close as limit_price, dn.next_close,
                si.industry, db.circ_mv,
                CASE WHEN (dn.open - dn.pre_close)/dn.pre_close*100 > 3 THEN 'fast' ELSE 'normal' END as open_type
            FROM daily_with_next dn
            JOIN stk_limit sl ON dn.ts_code = sl.ts_code AND dn.trade_date = sl.trade_date
            LEFT JOIN stock_info si ON SUBSTR(dn.ts_code, 1, LENGTH(dn.ts_code)-3) = si.stock_code
            LEFT JOIN daily_basic db ON dn.ts_code = db.ts_code AND dn.trade_date = db.trade_date
            WHERE dn.close >= sl.up_limit * 0.98
              AND dn.next_close IS NOT NULL
              AND si.industry IS NOT NULL
        )
        SELECT 
            industry, open_type,
            CASE WHEN circ_mv < 100000000 THEN '<1亿'
                 WHEN circ_mv < 500000000 THEN '1-5亿'
                 WHEN circ_mv < 2000000000 THEN '5-20亿'
                 ELSE '>20亿' END as size,
            COUNT(*) as cnt,
            ROUND(AVG((next_close - limit_price) / limit_price * 100), 2) as avg_return,
            ROUND(100 * SUM(CASE WHEN (next_close - limit_price) > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate
        FROM limit_days WHERE circ_mv IS NOT NULL
        GROUP BY industry, open_type, size
        HAVING cnt >= 5
        ORDER BY avg_return DESC LIMIT 20
    """).fetchall()
    
    print(f"\n{'行业':<8} {'开盘':>6} {'市值':>8} {'样本':>4} {'T+1%':>7} {'胜率':>6}")
    print("─" * 55)
    for r in results:
        star = "★★★" if float(r[5]) > 70 else "★" if float(r[5]) > 60 else ""
        print(f"{r[0]:<8} {r[1]:>6} {r[2]:>8} {r[3]:>4} "
              f"{r[4]:>+6.2f}% {r[5]:>5.1f}% {star}")

    con.close()

if __name__ == '__main__':
    print("板块共振分析 - 涨停股的行业效应")
    print(f"{'='*70}\n")
    
    analyze_industry_premium()
    analyze_sector_cluster()
    analyze_sector_momentum()
    analyze_optimal_strategy()
