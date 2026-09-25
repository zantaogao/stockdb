#!/usr/bin/env python3
"""回填 new_factors/flow_alpha/vol_adj 历史数据（最近 N 个交易日）"""
import duckdb
import numpy as np
import sys
from datetime import datetime, timedelta

conn = duckdb.connect('state.db')
conn.execute("ATTACH '/Users/zantao/.hermes/stockdb/tushare.db' AS t2 (READ_ONLY)")

# 确保三张表存在（与 new_factors.py 结构一致）
conn.execute("CREATE TABLE IF NOT EXISTS new_factors (date VARCHAR, stock_code VARCHAR, ma_decay DOUBLE, momentum_accel DOUBLE)")
conn.execute("CREATE TABLE IF NOT EXISTS flow_alpha (date VARCHAR, stock_code VARCHAR, flow_alpha DOUBLE, vol_ratio DOUBLE, price_dir DOUBLE)")
conn.execute("CREATE TABLE IF NOT EXISTS vol_adj (date VARCHAR, stock_code VARCHAR, vol_adj DOUBLE, price_volatility DOUBLE, volume_volatility DOUBLE, price_dir DOUBLE)")

# 取最近 N 个交易日（从 stock_daily 去重）
N = int(sys.argv[1]) if len(sys.argv) > 1 else 20
dates = [r[0] for r in conn.execute(
    "SELECT DISTINCT date FROM t2.stock_daily WHERE date IS NOT NULL ORDER BY date DESC LIMIT ?",
    (N,)).fetchall()]
# 只回填表中缺失的日期
existing = {r[0] for r in conn.execute("SELECT DISTINCT date FROM new_factors").fetchall()}
dates = [d for d in dates if str(d) not in existing]
print(f"回填 {len(dates)} 个缺失交易日: {dates[-1] if dates else '-'} ~ {dates[0] if dates else '-'}")

def calc_new_factors(today):
    rows = conn.execute(f"""
        WITH ranked AS (
            SELECT stock_code, date, close,
                ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY CAST(date AS DATE)) as rn,
                COUNT(*) OVER (PARTITION BY stock_code) as total_rn
            FROM t2.stock_daily
            WHERE CAST(date AS DATE) >= CAST('{today}' AS DATE) - INTERVAL '14 days'
              AND CAST(date AS DATE) <= CAST('{today}' AS DATE)
        ),
        latest AS (
            SELECT stock_code,
                MAX(CASE WHEN rn = total_rn THEN close END) as P_t,
                MAX(CASE WHEN rn = total_rn - 1 THEN close END) as c_t_2,
                MAX(CASE WHEN rn = total_rn - 2 THEN close END) as c_t_3,
                MAX(CASE WHEN rn = total_rn - 4 THEN close END) as P_t5,
                MAX(CASE WHEN rn = total_rn - 6 THEN close END) as P_t8
            FROM ranked GROUP BY stock_code
        )
        SELECT stock_code, P_t, P_t5, P_t8,
            (P_t - P_t5) / P_t5 as momentum_5d,
            (P_t - P_t8) / P_t8 as momentum_8d,
            ((P_t - P_t5) / P_t5 - (P_t - P_t8) / P_t8) / NULLIF(ABS((P_t - P_t8) / P_t8), 0) as ma_decay,
            (P_t - 2*c_t_2 + c_t_3) / NULLIF(ABS(P_t), 0) as momentum_accel
        FROM latest WHERE P_t5 > 0 AND P_t8 > 0
    """).fetchall()
    return rows

def calc_flow_alpha(today):
    rows = conn.execute(f"""
        WITH vol_stats AS (
            SELECT stock_code, AVG(volume) as avg_vol
            FROM t2.stock_daily
            WHERE CAST(date AS DATE) >= CAST('{today}' AS DATE) - INTERVAL '4 days'
              AND CAST(date AS DATE) <= CAST('{today}' AS DATE)
            GROUP BY stock_code
        ),
        ranked AS (
            SELECT stock_code, CAST(date AS DATE) as date, close,
                ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY CAST(date AS DATE)) as rn,
                COUNT(*) OVER (PARTITION BY stock_code) as total_rn
            FROM t2.stock_daily
            WHERE CAST(date AS DATE) >= CAST('{today}' AS DATE) - INTERVAL '4 days'
              AND CAST(date AS DATE) <= CAST('{today}' AS DATE)
        ),
        latest AS (
            SELECT stock_code,
                MAX(CASE WHEN rn = total_rn THEN close END) as P_t,
                MAX(CASE WHEN rn = total_rn - 1 THEN close END) as P_t_1
            FROM ranked GROUP BY stock_code
        ),
        price_dir AS (
            SELECT stock_code, (P_t - P_t_1) / NULLIF(P_t_1, 0) as price_dir
            FROM latest WHERE P_t_1 > 0
        )
        SELECT t2.stock_code, t2.volume / vs.avg_vol as vol_ratio,
            t2.change_pct / 100.0 as change_pct, pd.price_dir,
            POW(t2.volume / vs.avg_vol, 0.5) * COALESCE(pd.price_dir, 0.0) * (1 + ABS(t2.change_pct)/100.0) as flow_alpha
        FROM t2.stock_daily t2
        JOIN vol_stats vs ON t2.stock_code = vs.stock_code
        JOIN price_dir pd ON t2.stock_code = pd.stock_code
        WHERE CAST(t2.date AS DATE) = CAST('{today}' AS DATE)
    """).fetchall()
    return rows

def calc_vol_adj(today):
    rows = conn.execute(f"""
        WITH vol_stats AS (
            SELECT stock_code, AVG(volume) as avg_vol, STDDEV(volume) as stddev_vol
            FROM t2.stock_daily
            WHERE date >= '{today}'::date - INTERVAL '4 days' AND date <= '{today}'::date
            GROUP BY stock_code
        ),
        price_vol AS (
            SELECT stock_code,
                STDDEV(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) as price_std,
                AVG(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) as price_avg,
                date
            FROM t2.stock_daily
            WHERE date >= '{today}'::date - INTERVAL '4 days' AND date <= '{today}'::date
        ),
        latest_pv AS (
            SELECT stock_code, price_std, price_avg FROM price_vol WHERE date = '{today}'::date
        )
        SELECT t2.stock_code,
            pv.price_std / NULLIF(pv.price_avg, 0) as price_volatility,
            vs.stddev_vol / NULLIF(vs.avg_vol, 0) as volume_volatility,
            (pv.price_std / NULLIF(pv.price_avg, 0)) / NULLIF((vs.stddev_vol / NULLIF(vs.avg_vol, 0)), 0) as vol_adj,
            t2.change_pct / 100.0 as price_dir
        FROM t2.stock_daily t2
        JOIN vol_stats vs ON t2.stock_code = vs.stock_code
        JOIN latest_pv pv ON t2.stock_code = pv.stock_code
        WHERE t2.date = '{today}'::date AND vs.avg_vol > 0 AND vs.stddev_vol > 0 AND pv.price_avg > 0
    """).fetchall()
    return rows

total = 0
for d in dates:
    today = str(d)
    try:
        r1 = calc_new_factors(today)
        for r in r1:
            conn.execute(f"INSERT INTO new_factors VALUES ('{today}', '{r[0]}', {r[6] if r[6] is not None else 0.0}, {r[7] if r[7] is not None else 0.0})")
        r2 = calc_flow_alpha(today)
        for r in r2:
            conn.execute(f"INSERT INTO flow_alpha VALUES ('{today}', '{r[0]}', {r[4] if r[4] is not None else 0.0}, {r[1] if r[1] is not None else 0.0}, {r[3] if r[3] is not None else 0.0})")
        r3 = calc_vol_adj(today)
        for r in r3:
            conn.execute(f"INSERT INTO vol_adj VALUES ('{today}', '{r[0]}', {r[3] if r[3] is not None else 0.0}, {r[1] if r[1] is not None else 0.0}, {r[2] if r[2] is not None else 0.0}, {r[4] if r[4] is not None else 0.0})")
        conn.commit()
        total += len(r1)
        print(f"  {today}: new_factors={len(r1)} flow={len(r2)} vol={len(r3)}")
    except Exception as e:
        print(f"  {today}: ERROR {str(e)[:80]}")

print(f"\n回填完成，共 {total} 条 new_factors 记录")
conn.close()
