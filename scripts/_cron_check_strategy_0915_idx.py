#!/usr/bin/env python3
"""只读: 实时指数/持仓价 sanity check, 确认 NAV 变动由行情驱动"""
import sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.prices import fetch_price_live
for code in ['sh000001', 'sz399001', 'sh000300', 'sz399852', '000001']:
    try:
        print(code, fetch_price_live(code))
    except Exception as e:
        print(code, "EXC", type(e).__name__, e)
