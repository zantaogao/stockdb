import duckdb
import numpy as np

conn = duckdb.connect(str(__import__('pathlib').Path.home()/'.hermes/stockdb/signals.db'))  # v2温层,绝对路径
conn.execute("ATTACH '/Users/zantao/.hermes/stockdb/tushare.db' AS t2 (READ_ONLY)")
# 取最新交易日
latest_r = conn.execute("SELECT MAX(date) FROM t2.stock_daily WHERE date IS NOT NULL").fetchone()
today = str(latest_r[0]) if latest_r[0] else '2026-07-24'
print(f'最新交易日: {today}')

# 1. 创建并填充new_factors
print('=== 创建new_factors ===')
rows = conn.execute(f"""
    WITH ranked AS (
        SELECT 
            stock_code,
            date,
            close,
            ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY CAST(date AS DATE)) as rn,
            COUNT(*) OVER (PARTITION BY stock_code) as total_rn
        FROM t2.stock_daily
        WHERE CAST(date AS DATE) >= CAST('{today}' AS DATE) - INTERVAL '14 days'
          AND CAST(date AS DATE) <= CAST('{today}' AS DATE)
    ),
    latest AS (
        SELECT 
            stock_code,
            MAX(CASE WHEN rn = total_rn THEN close END) as P_t,
            MAX(CASE WHEN rn = total_rn - 1 THEN close END) as c_t_2,
            MAX(CASE WHEN rn = total_rn - 2 THEN close END) as c_t_3,
            MAX(CASE WHEN rn = total_rn - 4 THEN close END) as P_t5,
            MAX(CASE WHEN rn = total_rn - 6 THEN close END) as P_t8
        FROM ranked
        GROUP BY stock_code
    )
    SELECT 
        stock_code,
        P_t,
        P_t5,
        P_t8,
        (P_t - P_t5) / P_t5 as momentum_5d,
        (P_t - P_t8) / P_t8 as momentum_8d,
        ((P_t - P_t5) / P_t5 - (P_t - P_t8) / P_t8) / 
        NULLIF(ABS((P_t - P_t8) / P_t8), 0) as ma_decay,
        (P_t - 2*c_t_2 + c_t_3) / NULLIF(ABS(P_t), 0) as momentum_accel
    FROM latest
    WHERE P_t5 > 0 AND P_t8 > 0
""").fetchall()

print(f'MA_decay数据: {len(rows)}只股票')
ma_decay_vals = [r[6] for r in rows if r[6] is not None]
if len(ma_decay_vals) > 0:
    print(f'范围: {min(ma_decay_vals):.3f} ~ {max(ma_decay_vals):.3f}, 均值: {np.mean(ma_decay_vals):.3f}')

# 创建表并插入数据（保留历史：只删当天，累积多日供动态标准化）
conn.execute("CREATE TABLE IF NOT EXISTS new_factors (date VARCHAR, stock_code VARCHAR, ma_decay DOUBLE, momentum_accel DOUBLE)")
conn.execute(f"DELETE FROM new_factors WHERE date = '{today}'")
for r in rows:
    ma = r[6] if r[6] is not None else 0.0
    mom = r[7] if r[7] is not None else 0.0
    conn.execute(f"INSERT INTO new_factors VALUES ('{today}', '{r[0]}', {ma}, {mom})")
print(f'new_factors: {len(rows)}条记录（保留历史）')

# 2. 创建并填充flow_alpha
print('\n=== 创建flow_alpha ===')
rows2 = conn.execute(f"""
    WITH vol_stats AS (
        SELECT stock_code, AVG(volume) as avg_vol
        FROM t2.stock_daily
        WHERE CAST(date AS DATE) >= CAST('{today}' AS DATE) - INTERVAL '4 days'
          AND CAST(date AS DATE) <= CAST('{today}' AS DATE)
        GROUP BY stock_code
    ),
    ranked AS (
        SELECT 
            stock_code,
            CAST(date AS DATE) as date,
            close,
            ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY CAST(date AS DATE)) as rn,
            COUNT(*) OVER (PARTITION BY stock_code) as total_rn
        FROM t2.stock_daily
        WHERE CAST(date AS DATE) >= CAST('{today}' AS DATE) - INTERVAL '4 days'
          AND CAST(date AS DATE) <= CAST('{today}' AS DATE)
    ),
    latest AS (
        SELECT 
            stock_code,
            MAX(CASE WHEN rn = total_rn THEN close END) as P_t,
            MAX(CASE WHEN rn = total_rn - 1 THEN close END) as P_t_1
        FROM ranked
        GROUP BY stock_code
    ),
    price_dir AS (
        SELECT 
            stock_code,
            (P_t - P_t_1) / NULLIF(P_t_1, 0) as price_dir
        FROM latest
        WHERE P_t_1 > 0
    )
    SELECT 
        t2.stock_code,
        t2.volume / vs.avg_vol as vol_ratio,
        t2.change_pct / 100.0 as change_pct,
        pd.price_dir,
        POW(t2.volume / vs.avg_vol, 0.5) * COALESCE(pd.price_dir, 0.0) * (1 + ABS(t2.change_pct)/100.0) as flow_alpha
    FROM t2.stock_daily t2
    JOIN vol_stats vs ON t2.stock_code = vs.stock_code
    JOIN price_dir pd ON t2.stock_code = pd.stock_code
    WHERE CAST(t2.date AS DATE) = CAST('{today}' AS DATE)
""").fetchall()

print(f'flow_alpha数据: {len(rows2)}只股票')
flow_alpha_vals = [r[4] for r in rows2 if r[4] is not None]
if len(flow_alpha_vals) > 0:
    print(f'范围: {min(flow_alpha_vals):.3f} ~ {max(flow_alpha_vals):.3f}, 均值: {np.mean(flow_alpha_vals):.3f}')

conn.execute("CREATE TABLE IF NOT EXISTS flow_alpha (date VARCHAR, stock_code VARCHAR, flow_alpha DOUBLE, vol_ratio DOUBLE, price_dir DOUBLE)")
conn.execute(f"DELETE FROM flow_alpha WHERE date = '{today}'")
for r in rows2:
    conn.execute(f"INSERT INTO flow_alpha VALUES ('{today}', '{r[0]}', {r[4] if r[4] is not None else 0.0}, {r[1] if r[1] is not None else 0.0}, {r[3] if r[3] is not None else 0.0})")
print(f'flow_alpha: {len(rows2)}条记录（保留历史）')

# 3. 创建并填充vol_adj
print('\n=== 创建vol_adj ===')
rows3 = conn.execute(f"""
    WITH vol_stats AS (
        SELECT stock_code, AVG(volume) as avg_vol, STDDEV(volume) as stddev_vol
        FROM t2.stock_daily
        WHERE date >= '{today}'::date - INTERVAL '4 days'
          AND date <= '{today}'::date
        GROUP BY stock_code
    ),
    price_vol AS (
        SELECT stock_code,
            STDDEV(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) as price_std,
            AVG(close) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) as price_avg,
            date
        FROM t2.stock_daily
        WHERE date >= '{today}'::date - INTERVAL '4 days'
          AND date <= '{today}'::date
    ),
    latest_pv AS (
        SELECT stock_code, price_std, price_avg
        FROM price_vol
        WHERE date = '{today}'::date
    )
    SELECT 
        t2.stock_code,
        pv.price_std / NULLIF(pv.price_avg, 0) as price_volatility,
        vs.stddev_vol / NULLIF(vs.avg_vol, 0) as volume_volatility,
        (pv.price_std / NULLIF(pv.price_avg, 0)) / 
        NULLIF((vs.stddev_vol / NULLIF(vs.avg_vol, 0)), 0) as vol_adj,
        t2.change_pct / 100.0 as price_dir
    FROM t2.stock_daily t2
    JOIN vol_stats vs ON t2.stock_code = vs.stock_code
    JOIN latest_pv pv ON t2.stock_code = pv.stock_code
    WHERE t2.date = '{today}'::date
      AND vs.avg_vol > 0 AND vs.stddev_vol > 0
      AND pv.price_avg > 0
""").fetchall()

print(f'vol_adj数据: {len(rows3)}只股票')
vol_adj_vals = [r[3] for r in rows3 if r[3] is not None]
if len(vol_adj_vals) > 0:
    print(f'范围: {min(vol_adj_vals):.3f} ~ {max(vol_adj_vals):.3f}, 均值: {np.mean(vol_adj_vals):.3f}')

# 检查vol_adj数据
print(f'vol_adj数据: {len(rows3)}只股票')
vol_adj_vals = [r[3] for r in rows3 if r[3] is not None]
if len(vol_adj_vals) > 0:
    print(f'范围: {min(vol_adj_vals):.3f} ~ {max(vol_adj_vals):.3f}, 均值: {np.mean(vol_adj_vals):.3f}')
else:
    print(f'vol_adj数据: {len(rows3)}只股票 (无有效值)')
    for r in rows3[:5]:
        print(f'  {r}')

conn.execute("CREATE TABLE IF NOT EXISTS vol_adj (date VARCHAR, stock_code VARCHAR, vol_adj DOUBLE, price_volatility DOUBLE, volume_volatility DOUBLE, price_dir DOUBLE)")
conn.execute(f"DELETE FROM vol_adj WHERE date = '{today}'")
for r in rows3:
    conn.execute(f"INSERT INTO vol_adj VALUES ('{today}', '{r[0]}', {r[3] if r[3] is not None else 0.0}, {r[1] if r[1] is not None else 0.0}, {r[2] if r[2] is not None else 0.0}, {r[4] if r[4] is not None else 0.0})")
print(f'vol_adj: {len(rows3)}条记录（保留历史）')

# 4. 交叉验证
print('\n=== 交叉验证 ===')
corr = conn.execute("""
    SELECT 
        ROUND(CORR(nf.ma_decay, sh.reg10), 3) as ma_decay_reg10_corr,
        ROUND(CORR(fa.flow_alpha, sh.reg10), 3) as flow_alpha_reg10_corr,
        ROUND(CORR(va.vol_adj, sh.reg10), 3) as vol_adj_reg10_corr,
        ROUND(CORR(nf.ma_decay, fa.flow_alpha), 3) as ma_decay_flow_corr,
        ROUND(CORR(fa.flow_alpha, va.vol_adj), 3) as flow_vol_corr,
        ROUND(CORR(nf.ma_decay, va.vol_adj), 3) as ma_decay_vol_corr
    FROM new_factors nf
    JOIN signal_history sh ON nf.stock_code = sh.stock_code AND REPLACE(nf.date, '-', '') = REPLACE(sh.date, '-', '')
    JOIN flow_alpha fa ON nf.stock_code = fa.stock_code AND REPLACE(nf.date, '-', '') = REPLACE(fa.date, '-', '')
    JOIN vol_adj va ON nf.stock_code = va.stock_code AND REPLACE(nf.date, '-', '') = REPLACE(va.date, '-', '')
""").fetchone()

print(f'MA_decay与reg10相关性: {corr[0]}')
print(f'flow_alpha与reg10相关性: {corr[1]}')
print(f'vol_adj与reg10相关性: {corr[2]}')
print(f'MA_decay与flow_alpha相关性: {corr[3]}')
print(f'flow_alpha与vol_adj相关性: {corr[4]}')
print(f'MA_decay与vol_adj相关性: {corr[5]}')

# 5. 验证表是否真的存在
print('\n=== 验证表 ===')
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('new_factors', 'flow_alpha', 'vol_adj')").fetchall()
print('表列表:')
for t in tables:
    count = conn.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
    print(f'  {t[0]}: {count}条记录')

conn.close()
print('\n所有因子已写入signals.db！')
