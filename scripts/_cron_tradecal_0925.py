#!/usr/bin/env python3
"""用 tushare trade_cal 权威确认 20260925 是否交易日（不打印 token）"""
import json
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb')
cfg = json.loads((BASE / 'config.json').read_text())
tok = None
def dig(o):
    global tok
    if isinstance(o, dict):
        for k, v in o.items():
            if 'token' in k.lower() and isinstance(v, str) and len(v) > 10:
                tok = v
            dig(v)

dig(cfg)
print('token found:', bool(tok))
if tok:
    import tushare as ts
    pro = ts.pro_api(tok)
    df = pro.trade_cal(exchange='SSE', start_date='20260918', end_date='20261009')
    print(df.to_string())
