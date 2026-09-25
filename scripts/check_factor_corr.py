#!/usr/bin/env python3
"""
因子相关系数矩阵：检查多重共线性
输出：热力图数据 + 高相关因子对列表
"""
import duckdb
import numpy as np
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
TUSHARE_DB = BASE / 'tushare.db'

def main():
    factors = ['rsi_12', 'pct_chg', 'vol', 'amount', 'chg5', 'chg10', 'momentum_5d', 'reversal_1d']
    
    con = duckdb.connect(str(TUSHARE_DB), read_only=True)
    
    # 获取最近 30 天的因子数据 (取非空值)
    query = f"""
        SELECT ts_code, trade_date, {', '.join([f for f in factors if f not in ['momentum_5d', 'reversal_1d']])}
        FROM stk_factor
        WHERE trade_date >= (SELECT MAX(trade_date) FROM stk_factor) - INTERVAL '30' DAY
        AND {factors[0]} IS NOT NULL
        LIMIT 50000
    """
    
    try:
        df = con.execute(query).fetchdf()
        print(f"样本数: {len(df)}")
        
        if len(df) < 100:
            print("样本不足")
            return
        
        # 计算相关系数矩阵
        corr_matrix = df[factors[:6]].corr()  # 只取前 6 个因子
        
        print("\n=== 相关系数矩阵 ===")
        print(corr_matrix.round(3))
        
        # 找出高相关因子对 (|corr| > 0.8)
        print("\n=== 高相关因子对 (|corr| > 0.8) ===")
        high_corr = []
        cols = corr_matrix.columns
        for i in range(len(cols)):
            for j in range(i+1, len(cols)):
                corr_val = corr_matrix.iloc[i, j]
                if abs(corr_val) > 0.8:
                    high_corr.append((cols[i], cols[j], corr_val))
                    print(f"{cols[i]} vs {cols[j]}: {corr_val:.3f}")
        
        if not high_corr:
            print("无明显高相关因子对")
        
        # 保存矩阵到文件
        import json
        corr_data = {}
        for i, col1 in enumerate(cols):
            corr_data[col1] = {}
            for j, col2 in enumerate(cols):
                corr_data[col1][col2] = round(corr_matrix.iloc[i, j], 4)
        
        save_path = BASE / 'scripts/output/factor_corr.json'
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, 'w') as f:
            json.dump(corr_data, f, indent=2, ensure_ascii=False)
        print(f"\nSaved: {save_path}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        con.close()

if __name__ == '__main__':
    main()