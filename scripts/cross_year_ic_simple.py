#!/usr/bin/env python3
"""
简化版：逐年逐因子计算 IC，确保每一步都有输出
"""
import duckdb
import json
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
TUSHARE_DB = BASE / 'tushare.db'

def calc_ic_for_year_year(year, factor, con):
    """计算某年某因子的原始 IC 和取反 IC"""
    start_date = f"{year}0101"
    end_date = f"{year}1231"
    
    # 简化 SQL：直接计算相关性
    if factor == 'rsi_12':
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
    
    result = con.execute(query).fetchone()
    return result[0], result[1], result[2]

def main():
    factors = ['rsi_12', 'pct_chg', 'vol', 'amount']
    years = [2022, 2023, 2024, 2025, 2026]
    
    con = duckdb.connect(str(TUSHARE_DB), read_only=True)
    
    results = []
    
    for year in years:
        print(f"\n{'='*50}")
        print(f"Processing Year: {year}")
        print(f"{'='*50}")
        
        for factor in factors:
            try:
                print(f"  Calculating {factor}...", end=" ", flush=True)
                orig_ic, inv_ic, n = calc_ic_for_year_year(year, factor, con)
                
                if orig_ic is not None and n > 1000:
                    print(f"orig={orig_ic:.4f}, inv={inv_ic:.4f}, n={n}")
                    results.append({
                        'year': year,
                        'factor': factor,
                        'orig_ic': round(orig_ic, 4),
                        'inv_ic': round(inv_ic, 4),
                        'sample': n
                    })
                else:
                    print(f"N/A (n={n})")
            except Exception as e:
                print(f"Error: {e}")
                results.append({
                    'year': year,
                    'factor': factor,
                    'orig_ic': None,
                    'inv_ic': None,
                    'sample': 0,
                    'error': str(e)
                })
        
        # 每年保存一次
        with open(BASE / 'scripts/output/cross_year_ic_partial.json', 'w') as f:
            json.dump(results, f, indent=2)
    
    con.close()
    
    # 最终保存
    with open(BASE / 'scripts/output/cross_year_ic.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n{'='*50}")
    print("Final Results:")
    print(f"{'='*50}")
    for r in results:
        print(f"{r['year']} {r['factor']}: orig={r['orig_ic']}, inv={r['inv_ic']}, n={r['sample']}")
    
    print(f"\nSaved to: {BASE / 'scripts/output/cross_year_ic.json'}")

if __name__ == '__main__':
    main()