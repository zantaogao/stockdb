#!/usr/bin/env python3
"""多源交叉验证 2026-09-25 是否交易日"""
import sys
import urllib.request
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))

# 1) 腾讯行情
try:
    req = urllib.request.Request("https://qt.gtimg.cn/q=sh000852,sh000001,sz399001",
                                 headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=8).read().decode('gbk')
    print('--- TENCENT ---')
    for line in raw.strip().split('\n'):
        if '~' not in line:
            continue
        p = line.split('"')[1].split('~')
        # p[1]=name p[3]=now p[4]=prev p[30]=datetime p[31]=chg p[32]=pct
        print(f"{p[0]}: name={p[1]} now={p[3]} prev={p[4]} dt={p[30]} pct={p[32]}")
except Exception as e:
    print('TENCENT ERR', e)

# 2) 东财行情
try:
    u = "https://push2.eastmoney.com/api/qt/stock/get?secid=1.000852&fields=f43,f60,f169,f170,f86"
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=8).read().decode()
    print('--- EASTMONEY ---', raw[:400])
except Exception as e:
    print('EASTMONEY ERR', e)

# 3) tushare trade_cal
try:
    from core.db import get_db
    import duckdb
    print('--- tushare token ---')
    for p in [BASE / 'config.yaml', BASE / 'config.json', Path.home() / '.tushare.json']:
        if p.exists():
            print('found', p)
    tok = None
    import os, json
    for k in ('TUSHARE_TOKEN',):
        if os.environ.get(k):
            tok = os.environ[k]
    print('env token:', bool(tok))
except Exception as e:
    print('token probe err', e)
