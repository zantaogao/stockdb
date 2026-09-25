#!/usr/bin/env python3
"""盘前补充采集：美股个股隔夜涨跌 + 人民币汇率（premarket_data.py 两段失败时的兜底）
数据源（按优先级逐个试）：
  美股: ①sina hq gb_<sym> ②东财 stock_us_spot_em ③akshare stock_us_daily
  汇率: ①sina hq fx_susdcny ②akshare fx_spot_quote ③东财 forex_spot_em
"""
import sys, io, json, time, traceback
from pathlib import Path
BASE = Path('/Users/zantao/.hermes/stockdb')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import akshare as ak
import pandas as pd
import requests

SYMS = ['NVDA','MSFT','AAPL','TSLA','META','GOOG','AMZN','AVGO','MU','TSM','ASML','INTC','AMD',
        'BABA','KWEB','XPEV','NIO','LI']

def probe_ak_stock_us_daily():
    try:
        df = ak.stock_us_daily(symbol='NVDA')
        return ('ak.stock_us_daily OK', df.tail(2).to_string())
    except Exception as e:
        return (f'ak.stock_us_daily FAIL {type(e).__name__}: {str(e)[:120]}', None)

def probe_sina_hq():
    try:
        url = 'https://hq.sinajs.cn/list=' + ','.join('gb_' + s.lower() for s in SYMS[:3])
        r = requests.get(url, headers={'Referer': 'https://finance.sina.com.cn'}, timeout=10)
        r.encoding = 'gbk'
        return ('sina hq OK', r.text[:800])
    except Exception as e:
        return (f'sina hq FAIL {type(e).__name__}: {str(e)[:120]}', None)

def probe_us_spot_em():
    try:
        df = ak.stock_us_spot_em()
        cols = [c for c in df.columns][:8]
        return (f'stock_us_spot_em OK rows={len(df)} cols={cols}', df[cols].head(3).to_string())
    except Exception as e:
        return (f'stock_us_spot_em FAIL {type(e).__name__}: {str(e)[:120]}', None)

def probe_fx():
    out = []
    try:
        r = requests.get('https://hq.sinajs.cn/list=fx_susdcny,fx_seurcny,fx_sjpycny',
                         headers={'Referer': 'https://finance.sina.com.cn'}, timeout=10)
        r.encoding = 'gbk'
        out.append(('sina fx hq', r.text[:400]))
    except Exception as e:
        out.append(('sina fx hq FAIL', str(e)[:120]))
    try:
        df = ak.fx_spot_quote()
        out.append(('ak.fx_spot_quote', df.to_string()[:800]))
    except Exception as e:
        out.append(('ak.fx_spot_quote FAIL', str(e)[:120]))
    try:
        df = ak.currency_boc_sina(symbol='美元', start_date='20260910', end_date='20260916')
        out.append(('currency_boc_sina', df.tail(3).to_string()))
    except Exception as e:
        out.append(('currency_boc_sina FAIL', str(e)[:120]))
    return out

print('### ak.stock_us_daily ###')
m, d = probe_ak_stock_us_daily(); print(m); print(d)
print('\n### sina hq ###')
m, d = probe_sina_hq(); print(m); print(d)
print('\n### stock_us_spot_em ###')
m, d = probe_us_spot_em(); print(m); print(d)
print('\n### FX ###')
for m, d in probe_fx():
    print(m); print(d)
