#!/usr/bin/env python3
"""从 factor_daily_values 表中提取 Top 18 GTJA因子，生成扩展版 pickle

根据 gtja191_bench.csv 的 |IC| 排序，选 Top 18 因子 (|IC| > 0.04)
DB中的命名: gtja_alpha_XXX 或 gtja_alpha_XXX_inv (inv=取反过)
pickle中的命名: gtja_alpha_XXX (统一格式)
"""
import gzip, pickle, duckdb, numpy as np, pandas as pd
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
DB = BASE / 'stock.db'
OUT_PKL = BASE / 'gtja_signals_ext.pkl.gz'
BENCH = BASE / 'gtja191_bench.csv'

# Top 18 因子 (按bench |IC| 排序，DB中的实际因子名)
DB_FACTORS = [
    'gtja_alpha_150_inv',  # IC=0.084
    'gtja_alpha_158_inv',  # IC=0.070
    'gtja_alpha_159_inv',  # IC=0.066
    'gtja_alpha_167_inv',  # IC=0.060
    'gtja_alpha_175_inv',  # IC=0.053
    'gtja_alpha_187_inv',  # IC=0.051
    'gtja_alpha_184',      # IC=0.051 (positive)
    'gtja_alpha_168',      # IC=0.050 (positive)
    'gtja_alpha_189_inv',  # IC=0.049
    'gtja_alpha_147_inv',  # IC=0.049
    'gtja_alpha_151_inv',  # IC=0.049
    'gtja_alpha_161_inv',  # IC=0.047
    'gtja_alpha_177',      # IC=0.047 (positive)
    'gtja_alpha_157',      # IC=0.046 (positive)
    'gtja_alpha_144',      # IC=0.041 (positive)
    'gtja_alpha_156',      # IC=0.041 (positive)
    # 额外保留原有4因子中不在上面的
    'gtja_006',            # 原有因子
    'gtja_083',            # 原有因子
]

def main():
    print(f"从 factor_daily_values 提取 {len(DB_FACTORS)} 个因子...")
    con = duckdb.connect(str(DB), read_only=True)
    
    # 检查哪些因子在DB中存在
    factor_check = con.execute("""
        SELECT DISTINCT factor_name FROM factor_daily_values 
        WHERE factor_name LIKE 'gtja%' ORDER BY factor_name
    """).fetchall()
    db_factors = {r[0] for r in factor_check}
    print(f"DB中GTJA因子: {sorted(db_factors)}")
    
    available = [f for f in DB_FACTORS if f in db_factors]
    missing = [f for f in DB_FACTORS if f not in db_factors]
    print(f"可用: {len(available)}, 缺失: {missing}")
    
    result = {}
    for fname in available:
        rows = con.execute(f"""
            SELECT date, stock_code, raw_value 
            FROM factor_daily_values 
            WHERE factor_name='{fname}' 
            ORDER BY date, stock_code
        """).fetchdf()
        if len(rows) == 0:
            print(f"  {fname}: empty, skipping")
            continue
        # Pivot to DataFrame (date x stock_code)
        df = rows.pivot_table(index='date', columns='stock_code', values='raw_value')
        # Convert date index to string
        df.index = [str(d)[:10] for d in df.index]
        result[fname] = df
        print(f"  {fname}: {df.shape} ({df.index[0]} -> {df.index[-1]})")
    
    con.close()
    
    # 保存
    with gzip.open(str(OUT_PKL), 'wb') as f:
        pickle.dump(result, f)
    
    import os
    size = os.path.getsize(OUT_PKL)
    print(f"\nSaved: {OUT_PKL} ({size/1024/1024:.1f}MB, {len(result)} factors)")
    print("因子列表:")
    for k in sorted(result.keys()):
        print(f"  {k}")

if __name__ == '__main__':
    main()
