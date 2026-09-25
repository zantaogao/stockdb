"""
连板策略回测
============
分析首板→二板→三板...的胜率衰减曲线和平均次日溢价。

核心问题: 连到第几板最赚？什么时候该走？
"""

import duckdb
import os
from collections import defaultdict

DB_PATH = os.path.expanduser('~/.hermes/stockdb/tushare.db')

def safe_connect():
    """安全连接，处理WAL残留"""
    wal = DB_PATH + '.wal'
    try:
        con = duckdb.connect(str(DB_PATH), read_only=True)
        return con
    except Exception:
        if os.path.exists(wal):
            os.remove(wal)
        return duckdb.connect(str(DB_PATH), read_only=True)

def analyze_board_streaks():
    """分析连板天数 vs 次日表现"""
    con = safe_connect()
    
    print("=" * 70)
    print("连板策略回测: 首板→二板→三板→...")
    print("=" * 70)
    
    # 识别所有涨停日，并计算连续涨停天数
    results = con.execute("""
        WITH daily_with_next AS (
            SELECT 
                ts_code, trade_date, close, open, pct_chg, pre_close,
                LEAD(close) OVER w as next_close,
                LEAD(trade_date) OVER w as next_date
            FROM daily WHERE ts_code LIKE '0%' AND trade_date >= '20250101'
            WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date ASC)
        ),
        limit_days AS (
            SELECT 
                dn.ts_code,
                dn.trade_date as limit_date,
                dn.close as limit_price,
                dn.next_close,
                ROUND(dn.pct_chg, 2) as pct_chg
            FROM daily_with_next dn
            JOIN stk_limit sl ON dn.ts_code = sl.ts_code AND dn.trade_date = sl.trade_date
            WHERE dn.close >= sl.up_limit * 0.98
              AND dn.next_close IS NOT NULL
        ),
        with_streak AS (
            SELECT 
                ld.*,
                -- 计算连续涨停天数：往前数有多少天也涨停了
                (SELECT COUNT(*) FROM limit_days prev
                 WHERE prev.ts_code = ld.ts_code 
                   AND CAST(prev.limit_date AS INTEGER) > CAST(ld.limit_date AS INTEGER) - 10
                   AND CAST(prev.limit_date AS INTEGER) < CAST(ld.limit_date AS INTEGER)) + 1 as streak_day,
                -- T+1收益
                ROUND((ld.next_close - ld.limit_price) / ld.limit_price * 100, 3) as t1_return
            FROM limit_days ld
        )
        SELECT 
            streak_day as board_num,
            COUNT(*) as cnt,
            ROUND(AVG(t1_return), 2) as avg_t1_return,
            ROUND(100 * SUM(CASE WHEN t1_return > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate,
            ROUND(MAX(t1_return), 2) as max_return,
            ROUND(MIN(t1_return), 2) as min_return,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY t1_return) as p75,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY t1_return) as p25
        FROM with_streak
        WHERE streak_day <= 8  -- 只看前8板
        GROUP BY streak_day
        ORDER BY streak_day
    """).fetchall()
    
    print(f"\n{'板数':>4} {'样本数':>6} {'均值%':>7} {'胜率%':>7} {'P75':>7} {'P25':>7}")
    print("─" * 50)
    
    for r in results:
        bar = '#' * int(r[3] / 3)  # 用胜率画条
        print(f"{r[0]:>4}板 {r[1]:>6} {r[2]:>+6.2f}% "
              f"{r[3]:>5.1f}% {r[4]:>+6.1f} {r[5]:>+6.1f}")
    
    # ===== 连板后的最佳卖出时机 =====
    print("\n\n=== 连板后 N 日收益 ===")
    
    # 用两层 CTE 避免嵌套 window function
    multi_day = con.execute("""
        WITH base AS (
            SELECT ts_code, trade_date, close, pct_chg, pre_close
            FROM daily WHERE ts_code LIKE '0%' AND trade_date >= '20250601'
        ),
        with_lead AS (
            SELECT 
                *, LEAD(close) OVER w as d1_close
            FROM base WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date ASC)
        ),
        with_d2 AS (
            SELECT *, LEAD(d1_close) OVER w2 as d2_close
            FROM with_lead WINDOW w2 AS (PARTITION BY ts_code ORDER BY trade_date ASC)
        ),
        limit_days AS (
            SELECT 
                wd.ts_code,
                wd.trade_date as limit_date,
                wd.close as limit_price,
                wd.d1_close,
                wd.d2_close
            FROM with_d2 wd
            JOIN stk_limit sl ON wd.ts_code = sl.ts_code AND wd.trade_date = sl.trade_date
            WHERE wd.close >= sl.up_limit * 0.98
              AND wd.d1_close IS NOT NULL
        )
        SELECT 
            ROUND(AVG((d1_close - limit_price) / limit_price * 100), 2) as t1,
            ROUND(AVG(CASE WHEN d2_close IS NOT NULL THEN (d2_close - limit_price) / limit_price * 100 ELSE NULL END), 2) as t2
        FROM limit_days
    """).fetchone()
    
    print(f"\nT+1均值: +{multi_day[0]}%")
    if len(multi_day) > 1 and multi_day[1] is not None:
        print(f"T+2均值: +{multi_day[1]}%")
    
    con.close()

def analyze_fast_vs_slow_streak():
    """快板(高开涨停) vs 慢板的连板能力"""
    con = safe_connect()
    
    print("\n\n=== 快板 vs 慢板的连板率 ===")
    
    streak_compare = con.execute("""
        WITH daily_with_next AS (
            SELECT 
                ts_code, trade_date, close, open, pct_chg, pre_close,
                LEAD(close) OVER w as next_close,
                LEAD(trade_date) OVER w as next_date
            FROM daily WHERE ts_code LIKE '0%' AND trade_date >= '20250601'
            WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date ASC)
        ),
        limit_days AS (
            SELECT 
                dn.ts_code,
                dn.trade_date as limit_date,
                dn.close as limit_price,
                dn.next_close,
                CASE WHEN (dn.open - dn.pre_close)/dn.pre_close*100 > 3 THEN 'fast' ELSE 'normal/slow' END as board_type
            FROM daily_with_next dn
            JOIN stk_limit sl ON dn.ts_code = sl.ts_code AND dn.trade_date = sl.trade_date
            WHERE dn.close >= sl.up_limit * 0.98
              AND dn.next_close IS NOT NULL
        )
        SELECT 
            board_type,
            COUNT(*) as cnt,
            -- 次日是否继续涨停的概率 (T+1也涨停)
            ROUND(100 * SUM(CASE WHEN next_close >= limit_price * 1.09 THEN 1 ELSE 0 END) / COUNT(*), 1) as cont_limit_rate,
            -- T+1收益
            ROUND(AVG((next_close - limit_price) / limit_price * 100), 2) as avg_return,
            ROUND(100 * SUM(CASE WHEN (next_close - limit_price) > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate
        FROM limit_days
        GROUP BY board_type
    """).fetchall()
    
    for r in streak_compare:
        print(f"  {r[0]:<12}: n={r[1]}, 连板率{r[2]}%, T+1均值{r[3]:+.2f}%, 胜率{r[4]}%")
    
    con.close()

def analyze_sector_rotation():
    """板块轮动: 哪些行业涨停集中时次日最强"""
    con = safe_connect()
    
    print("\n\n=== 板块集中度 vs 次日溢价 ===")
    
    # 检查是否有行业信息表
    tables = con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    industry_tables = [t[0] for t in tables if 'board' in t[0].lower() or 'industry' in t[0].lower()]
    print(f"  板块相关表: {industry_tables}")
    
    # 用 stock_info 里的 industry 字段
    if con.execute("SELECT COUNT(*) FROM pragma_table_info('stock_info')").fetchone()[0] > 5:
        has_industry = 'industry' in [c[1] for c in con.execute("PRAGMA table_info(stock_info)").fetchall()]
    else:
        has_industry = False
    
    if not has_industry:
        # 用 board_daily (如果存在)
        if 'board_kline' in [t[0] for t in tables] or 'index_board_raw' in [t[0] for t in tables]:
            print("  有板块日线数据，可以用")
    
    con.close()

if __name__ == '__main__':
    analyze_board_streaks()
    analyze_fast_vs_slow_streak()
    # analyze_sector_rotation()  # 需要板块表支持
