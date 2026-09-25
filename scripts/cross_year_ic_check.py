#!/usr/bin/env python3
"""
跨年度 IC 验证：检查取反策略在 2022-2026 年的稳定性
目标：确认 2026 年的“负向有效”是特例还是长期规律
"""
import duckdb
import numpy as np
import pandas as pd
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
TUSHARE_DB = BASE / 'tushare.db'

def calculate_year_ic(year, factor_name, con):
    """计算某一年某因子的原始 IC 和取反 IC"""
    # 构建日期范围
    start_date = f"{year}0101"
    end_date = f"{year}1231"
    
    # SQL: 计算因子值与未来 20 日收益的相关性
    # 注意：trade_date 是 VARCHAR，需要 CAST
    query = f"""
        WITH factor_ret AS (
            SELECT 
                f.trade_date,
                CAST(f.{factor_name} AS DOUBLE) as factor_val,
                (d.close - f_close) / f_close * 100 as ret_20d
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
            WHERE CAST(f.trade_date AS INTEGER) BETWEEN {year}0101 AND {year}1231
            AND f.{factor_name} IS NOT NULL
        )
        SELECT 
            CORR(factor_val, ret_20d) as orig_ic,
            CORR(
                CASE WHEN '{factor_name}'='rsi_12' THEN 100 - factor_val ELSE -factor_val END,
                ret_20d
            ) as inv_ic,
            COUNT(*) as sample_count
        FROM factor_ret
    """
    
    try:
        result = con.execute(query).fetchone()
        if result and result[2] > 1000:  # 样本量足够
            return result[0], result[1], result[2]
        else:
            return None, None, result[2] if result else 0
    except Exception as e:
        print(f"Error calculating IC for {year} {factor_name}: {e}")
        return None, None, 0

def main():
    factors = ['rsi_12', 'pct_chg', 'vol', 'amount', 'momentum_5d']
    years = [2022, 2023, 2024, 2025, 2026]
    
    con = duckdb.connect(str(TUSHARE_DB), read_only=True)
    
    print(f"Starting cross-year IC analysis...")
    print(f"Factors: {factors}")
    print(f"Years: {years}")
    print("-" * 70)
    
    all_results = []
    
    for year in years:
        print(f"\nProcessing year: {year}...")
        for factor in factors:
            try:
                orig_ic, inv_ic, sample_cnt = calculate_year_ic(year, factor, con)
                
                if orig_ic is not None:
                    # 判断取反是否有效
                    if inv_ic > orig_ic and inv_ic > 0.1:
                        conclusion = "✅ 取反有效"
                    elif orig_ic > inv_ic and orig_ic > 0.1:
                        conclusion = "❌ 保持原样"
                    elif abs(orig_ic) < 0.05 and abs(inv_ic) < 0.05:
                        conclusion = "⚪ 无效"
                    else:
                        conclusion = "⚠️ 微弱"
                    
                    print(f"  {factor}: orig={orig_ic:.4f}, inv={inv_ic:.4f}, n={sample_cnt} -> {conclusion}")
                    
                    all_results.append({
                        'year': year,
                        'factor': factor,
                        'orig_ic': round(orig_ic, 4),
                        'inv_ic': round(inv_ic, 4),
                        'sample': sample_cnt
                    })
                else:
                    print(f"  {factor}: N/A (n={sample_cnt})")
                    
            except Exception as e:
                print(f"  {factor}: Error - {e}")
                all_results.append({
                    'year': year,
                    'factor': factor,
                    'orig_ic': None,
                    'inv_ic': None,
                    'sample': 0,
                    'error': str(e)
                })
        
        # 每年结束后保存一次中间结果
        if year in [2024, 2025]:  # 中途保存
            import json
            save_path = BASE / 'scripts/output/cross_year_ic_partial.json'
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w') as f:
                json.dump(all_results, f, indent=2)
            print(f"  -> Saved partial results to {save_path}")
    
    con.close()
    
    # 最终保存
    import json
    save_path = BASE / 'scripts/output/cross_year_ic.json'
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f"\n=== Final Results Saved: {save_path} ===")
    
    # 简单趋势分析
    print("\n=== 趋势总结 ===")
    for factor in factors:
        factor_data = [r for r in all_results if r['factor'] == factor]
        if len(factor_data) >= 4:
            orig_avg = np.mean([r['orig_ic'] for r in factor_data if r['orig_ic'] is not None])
            inv_avg = np.mean([r['inv_ic'] for r in factor_data if r['inv_ic'] is not None])
            print(f"{factor}: 5年均值 原始={orig_avg:.3f}, 取反={inv_avg:.3f}")
            if inv_avg > orig_avg + 0.1:
                print(f"  -> 建议：长期取反有效")
            elif orig_avg > inv_avg + 0.1:
                print(f"  -> 建议：长期保持原样")
            else:
                print(f"  -> 建议：需动态调整（2026 年特殊？）")
    
    print("\nDone!")