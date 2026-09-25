#!/usr/bin/env python3
"""调试AKShare限流问题"""
import akshare as ak
import time

# 试一只股票
for i in range(3):
    try:
        t0 = time.time()
        df = ak.stock_individual_fund_flow(stock="002236", market="sz")
        print(f"尝试{i+1}: {len(df)}条, {time.time()-t0:.1f}s")
        if len(df) > 0:
            print(f"  范围: {df['日期'].min()} ~ {df['日期'].max()}")
    except Exception as e:
        print(f"尝试{i+1}: 失败 - {e}")
    time.sleep(2)

# 再试一只沪市的
for i in range(3):
    try:
        t0 = time.time()
        df = ak.stock_individual_fund_flow(stock="601868", market="sh")
        print(f"沪市尝试{i+1}: {len(df)}条, {time.time()-t0:.1f}s")
    except Exception as e:
        print(f"沪市尝试{i+1}: 失败 - {e}")
    time.sleep(2)
