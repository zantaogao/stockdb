#!/usr/bin/env python3
import duckdb
from scipy import stats as sp_stats
import numpy as np

conn = duckdb.connect('/Users/zantao/.hermes/stockdb/state.db')

print('=== 批量计算 IC (最近 5 个交易日) ===\n')

dates = conn.execute("""
    SELECT DISTINCT s1.date
    FROM stock_daily s1
    JOIN stock_daily s2 ON s1.stock_code = s2.stock_code AND s2.date > s1.date
    ORDER BY s1.date DESC
    LIMIT 5
""").fetchall()

print(f'目标日期：{[d[0] for d in dates]}\n')

ic_records = []

for (target_date,) in dates:
    next_date = conn.execute(f"SELECT MIN(date) FROM stock_daily WHERE date > '{target_date}'").fetchone()[0]
    
    data = conn.execute(f"""
        SELECT s1.change_pct, s2.change_pct
        FROM stock_daily s1
        JOIN stock_daily s2 ON s1.stock_code = s2.stock_code
        WHERE s1.date = '{target_date}' AND s2.date = '{next_date}'
          AND s1.change_pct IS NOT NULL AND s2.change_pct IS NOT NULL
    """).fetchall()
    
    if len(data) >= 30:
        fv = np.array([r[0] for r in data])
        rv = np.array([r[1] for r in data])
        mask = np.isfinite(fv) & np.isfinite(rv)
        fv_clean, rv_clean = fv[mask], rv[mask]
        
        if len(fv_clean) >= 30:
            rho, pval = sp_stats.spearmanr(fv_clean, rv_clean)
            ic_records.append((target_date, 'mom_1d', round(rho, 6), round(pval, 6), len(fv_clean), 1))
            print(f'{target_date} -> {next_date}: mom_1d IC = {rho:.4f} (n={len(fv_clean)})')

if ic_records:
    print(f'\n写入 {len(ic_records)} 条 IC 记录...')
    # 先删除旧数据再插入
    for rec in ic_records:
        conn.execute(f"DELETE FROM factor_ic_daily WHERE date='{rec[0]}' AND factor_name='{rec[1]}' AND ret_horizon={rec[5]}")
    conn.executemany(
        "INSERT INTO factor_ic_daily (date, factor_name, rank_ic, p_value, n_stocks, ret_horizon) VALUES (?, ?, ?, ?, ?, ?)",
        ic_records
    )
    conn.commit()
    print('完成！')
else:
    print('无 IC 记录')

print('\n=== factor_ic_daily 当前数据 ===')
for r in conn.execute('SELECT * FROM factor_ic_daily ORDER BY date DESC LIMIT 10').fetchall():
    print(f'  {r}')

conn.close()
