#!/usr/bin/env python3
"""
分块计算 IC：按月计算后加权平均，避免内存溢出
"""
import duckdb
import json
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
TUSHARE_DB = BASE / 'tushare.db'

def calc_ic_chunked(year, factor, con):
    """按月计算 IC，然后加权平均"""
    results = []
    
    # 1-12月
    for month in range(1, 13):
        start_date = f"{year}{month:02d}01"
        # 简单处理：假设每月 30 天，实际可用日期范围
        end_date = f"{year}{month:02d}30"
        
        # 调整结束日期（简单处理，避免跨月）
        if month == 12:
            end_date = f"{year}1231"
        
        # 构建表达式
        if factor == 'rsi_12':
            orig_expr = f"100.0 - CAST(f.{factor} AS DOUBLE)"  # 取反
            inv_expr = f"CAST(f.{factor} AS DOUBLE)"           # 原始 (这里逻辑反了，修正：orig=原始, inv=取反)
            # 修正：
            orig_expr = f"CAST(f.{factor} AS DOUBLE)"
            inv_expr = f"100.0 - CAST(f.{factor} AS DOUBLE)"
        else:
            orig_expr = f"CAST(f.{factor} AS DOUBLE)"
            inv_expr = f"-CAST(f.{factor} AS DOUBLE)"
        
        query = f"""
            WITH base AS (
                SELECT 
                    {orig_expr} as orig_val,
                    {inv_expr} as inv_val,
                    (d.close - f_close) / f_close * 100.0 as ret_20d
                FROM stk_factor f
                JOIN (
                    SELECT ts_code, trade_date, close as f_close
                    FROM daily
                ) d1 ON f.ts_code = d1.ts_code AND f.trade_date = d1.trade_date
                JOIN daily d ON d.ts_code = f.ts_code 
                    AND d.trade_date = (
                        SELECT trade_date FROM daily 
                        WHERE ts_code = f.ts_code 
                        AND trade_date > f.trade_date 
                        ORDER BY trade_date LIMIT 1 OFFSET 20
                    )
                WHERE CAST(f.trade_date AS INTEGER) BETWEEN {start_date} AND {end_date}
                AND f.{factor} IS NOT NULL
            )
            SELECT 
                CORR(orig_val, ret_20d) as orig_ic,
                CORR(inv_val, ret_20d) as inv_ic,
                COUNT(*) as n
            FROM base
        """
        
        try:
            res = con.execute(query).fetchone()
            if res and res[2] > 100:  # 每月至少 100 个样本
                results.append({
                    'orig_ic': res[0],
                    'inv_ic': res[1],
                    'n': res[2]
                })
        except Exception as e:
            # 月份数据可能不足，跳过
            pass
    
    if not results:
        return None, None, 0
    
    # 加权平均 (按样本数加权)
    total_n = sum(r['n'] for r in results)
    weighted_orig_ic = sum(r['orig_ic'] * r['n'] for r in results) / total_n
    weighted_inv_ic = sum(r['inv_ic'] * r['n'] for r in results) / total_n
    
    return weighted_orig_ic, weighted_inv_ic, total_n

def main():
    factors = ['rsi_12', 'pct_chg', 'vol', 'amount']
    years = [2022, 2023, 2024, 2025, 2026]
    
    con = duckdb.connect(str(TUSHARE_DB), read_only=True)
    
    results = []
    
    for year in years:
        print(f"\nYear: {year}")
        for factor in factors:
            try:
                orig_ic, inv_ic, n = calc_ic_chunked(year, factor, con)
                if orig_ic is not None:
                    print(f"  {factor}: orig={orig_ic:.4f}, inv={inv_ic:.4f}, n={n}")
                    results.append({
                        'year': year,
                        'factor': factor,
                        'orig_ic': round(orig_ic, 4),
                        'inv_ic': round(inv_ic, 4),
                        'sample': n
                    })
                else:
                    print(f"  {factor}: N/A")
            except Exception as e:
                print(f"  {factor}: Error - {e}")
                results.append({
                    'year': year,
                    'factor': factor,
                    'orig_ic': None,
                    'inv_ic': None,
                    'sample': 0,
                    'error': str(e)
                })
    
    con.close()
    
    # 保存
    save_path = BASE / 'scripts/output/cross_year_ic_chunked.json'
    with open(save_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nSaved: {save_path}")
    print("\n=== Summary ===")
    for r in results:
        if r['orig_ic'] is not None:
            print(f"{r['year']} {r['factor']}: orig={r['orig_ic']:.4f}, inv={r['inv_ic']:.4f}")

if __name__ == '__main__':
    main()