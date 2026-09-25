#!/usr/bin/env python3
"""
验证：用最近20天数据计算动态标准化参数，看是否比固定参数更合理
"""
import sqlite3
import numpy as np

STATE_DB = '/Users/zantao/.hermes/stockdb/state.db'
conn = sqlite3.connect(STATE_DB, timeout=10)

result2 = conn.execute("""
    SELECT 
        nf.ma_decay, 
        fa.flow_alpha, 
        va.vol_adj
    FROM new_factors nf
    LEFT JOIN flow_alpha fa 
        ON REPLACE(nf.stock_code, '.', '') = REPLACE(fa.stock_code, '.', '')
        AND REPLACE(nf.date, '-', '') = REPLACE(fa.date, '-', '')
    LEFT JOIN vol_adj va 
        ON REPLACE(nf.stock_code, '.', '') = REPLACE(va.stock_code, '.', '')
        AND REPLACE(nf.date, '-', '') = REPLACE(va.date, '-', '')
    WHERE REPLACE(nf.date, '-', '') >= '20260712'
      AND REPLACE(nf.date, '-', '') <= '20260731'
      AND nf.ma_decay IS NOT NULL
      AND fa.flow_alpha IS NOT NULL
      AND va.vol_adj IS NOT NULL
""").fetchall()

print(f"有效样本数: {len(result2)}")

if result2:
    ma_vals = [r[0] for r in result2 if r[0] is not None]
    flow_vals = [r[1] for r in result2 if r[1] is not None]
    vol_vals = [r[2] for r in result2 if r[2] is not None]
    
    print(f"\n=== 最近20天动态参数 ===")
    print(f"ma_decay:   mean={np.mean(ma_vals):.4f}  std={np.std(ma_vals):.4f}")
    print(f"flow_alpha: mean={np.mean(flow_vals):.4f}  std={np.std(flow_vals):.4f}")
    print(f"vol_adj:    mean={np.mean(vol_vals):.4f}  std={np.std(vol_vals):.4f}")
    
    print(f"\n=== 当前固定参数 ===")
    print(f"ma_decay:   mean=1.347   std=28.5")
    print(f"flow_alpha: mean=-0.023  std=0.012")
    print(f"vol_adj:    mean=0.110   std=0.075")
    
    print(f"\n=== 差异 ===")
    print(f"ma_decay mean差: {np.mean(ma_vals) - 1.347:.4f} ({'偏大' if np.mean(ma_vals) > 1.347 else '偏小'})")
    print(f"flow_alpha mean差: {np.mean(flow_vals) - (-0.023):.4f} ({'偏大' if np.mean(flow_vals) > -0.023 else '偏小'})")
    print(f"vol_adj mean差: {np.mean(vol_vals) - 0.110:.4f} ({'偏大' if np.mean(vol_vals) > 0.110 else '偏小'})")

conn.close()
