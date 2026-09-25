#!/usr/bin/env python3
"""
扫描 38 个特征的 IC：原始 vs 取反
输出：哪些特征取反后 IC > 0.1（有效）
"""
import duckdb
import json
import sys
from pathlib import Path

# 动态导入特征名
sys.path.insert(0, str(Path.home() / '.hermes' / 'stockdb' / 'scripts'))
from feat_tushare import BASE_FEAT_NAMES

BASE = Path.home() / '.hermes' / 'stockdb'
TUSHARE_DB = BASE / 'tushare.db'

def calc_ic_for_feature(feature, year, con):
    """计算某年某特征的原始 IC 和取反 IC"""
    start_date = f"{year}0101"
    end_date = f"{year}1231"
    
    # 构建 SQL
    query = f"""
        WITH base AS (
            SELECT 
                CAST(f.{feature} AS DOUBLE) as orig_val,
                -CAST(f.{feature} AS DOUBLE) as inv_val,
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
            AND f.{feature} IS NOT NULL
            AND f.{feature} != 0  -- 过滤掉全 0 的特征（如 rsi_12）
        )
        SELECT 
            CORR(orig_val, ret_20d) as orig_ic,
            CORR(inv_val, ret_20d) as inv_ic,
            COUNT(*) as n
        FROM base
    """
    
    try:
        result = con.execute(query).fetchone()
        return result[0], result[1], result[2]
    except Exception as e:
        return None, None, 0

def main():
    years = [2022, 2023, 2024, 2025, 2026]
    
    print(f"Scanning {len(BASE_FEAT_NAMES)} features across {len(years)} years...")
    print(f"Features: {BASE_FEAT_NAMES[:5]}... (total {len(BASE_FEAT_NAMES)})")
    
    con = duckdb.connect(str(TUSHARE_DB), read_only=True)
    
    all_results = []
    effective_features = []  # 取反后 IC > 0.1 的特征
    
    for feature in BASE_FEAT_NAMES:
        print(f"\n{'='*60}")
        print(f"Feature: {feature}")
        print(f"{'='*60}")
        
        year_results = []
        for year in years:
            orig_ic, inv_ic, n = calc_ic_for_feature(feature, year, con)
            
            if orig_ic is not None and n > 1000:
                print(f"  {year}: orig={orig_ic:.4f}, inv={inv_ic:.4f}, n={n}")
                year_results.append({
                    'year': year,
                    'orig_ic': round(orig_ic, 4),
                    'inv_ic': round(inv_ic, 4),
                    'sample': n
                })
                
                # 检查 2026 年是否有效
                if year == 2026 and abs(inv_ic) > 0.1:
                    if inv_ic > 0:
                        effective_features.append({
                            'feature': feature,
                            'type': 'inverted',
                            'ic_2026': inv_ic,
                            'ic_orig_2026': orig_ic
                        })
                    else:
                        effective_features.append({
                            'feature': feature,
                            'type': 'original',
                            'ic_2026': orig_ic,
                            'ic_inv_2026': inv_ic
                        })
            else:
                print(f"  {year}: N/A (n={n})")
        
        # 保存中间结果
        all_results.append({
            'feature': feature,
            'years': year_results
        })
    
    con.close()
    
    # 保存完整结果
    save_path = BASE / 'scripts/output/all_features_ic.json'
    with open(save_path, 'w') as f:
        json.dump(all_results, f, indent=2)
    
    # 保存有效特征列表
    eff_path = BASE / 'scripts/output/effective_features_2026.json'
    with open(eff_path, 'w') as f:
        json.dump(effective_features, f, indent=2)
    
    print(f"\n{'='*60}")
    print("SUMMARY: Effective Features for 2026 (|IC| > 0.1)")
    print(f"{'='*60}")
    
    if effective_features:
        for ef in effective_features:
            if ef['type'] == 'inverted':
                print(f"  ✅ {ef['feature']}: 取反有效 (IC={ef['ic_2026']:.4f}, 原={ef['ic_orig_2026']:.4f})")
            else:
                print(f"  ✅ {ef['feature']}: 原值有效 (IC={ef['ic_2026']:.4f})")
    else:
        print("  ⚠️  没有特征在 2026 年 IC > 0.1（区分度弱）")
    
    print(f"\nSaved: {save_path}")
    print(f"Effective features: {eff_path}")

if __name__ == '__main__':
    main()