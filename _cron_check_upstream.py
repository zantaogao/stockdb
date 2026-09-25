#!/usr/bin/env python3
"""验证 tushare 上游 stk_factor_pro 08-07 是否已完整 2026-08-08"""
import sys, json
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')

from update_tushare_api import get_pro
pro = get_pro()
for d in ['20260807', '20260806']:
    try:
        df = pro.stk_factor_pro(trade_date=d)
        n = 0 if df is None else len(df)
        print(f"上游 stk_factor_pro {d}: {n} 行")
        if df is not None and n > 0:
            print(f"  列数: {len(df.columns)}, 样例列: {list(df.columns)[:8]}")
            # 检查因子是否有值（非全 None/0）
            import pandas as pd
            sample = df.iloc[0]
            kdj = sample.get('kdj_k_bfq')
            print(f"  首行 kdj_k_bfq={kdj}, macd_dif={sample.get('macd_dif')}")
    except Exception as e:
        print(f"上游 {d}: 错误 {str(e)[:120]}")
