#!/usr/bin/env python3
"""只查 tushare 源头 fund_daily 今日是否有数（不写库）"""
import sys, json
from pathlib import Path
sys.path.insert(0, "/Users/zantao/.hermes/stockdb")
import tushare as ts
pro = ts.pro_api()
try:
    df = pro.fund_daily(trade_date='20260929')
    print(json.dumps({"rows": 0 if df is None else len(df)}))
    if df is not None and len(df):
        print(df.head(3).to_string())
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
