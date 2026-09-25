#!/usr/bin/env python3
"""盘前补充：用东财 push2his 日K 拉隔夜美股 18 只标的最近 3 个交易日真实收盘涨跌（含中概）
secid 市场码：105=纳斯达克 106=纽交所 107=美交所
输出格式：  代码: 最新收盘 x.xx 涨跌 +x.xx% [日期]   ← 自算，来自日K收盘价对收盘价
"""
import sys, io, json, time
from pathlib import Path
BASE = Path('/Users/zantao/.hermes/stockdb')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import requests

SYMS = [('NVDA', [105]), ('MSFT', [105]), ('AAPL', [105]), ('TSLA', [105]), ('META', [105]),
        ('GOOG', [105]), ('AMZN', [105]), ('AVGO', [105]), ('MU', [105]), ('TSM', [106]),
        ('ASML', [105, 106]), ('INTC', [105]), ('AMD', [105]), ('BABA', [106]),
        ('KWEB', [106, 107]), ('XPEV', [106]), ('NIO', [106]), ('LI', [105, 106])]

S = requests.Session()
S.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'})

def kline(code, mk):
    url = ('https://push2his.eastmoney.com/api/qt/stock/kline/get'
           f'?secid={mk}.{code}&fields1=f1,f2,f3,f4&fields2=f51,f52,f53,f54,f55,f56,f57,f58'
           '&klt=101&fqt=1&end=20500101&lmt=4')
    r = S.get(url, timeout=12)
    j = r.json()
    d = (j or {}).get('data')
    if not d or not d.get('klines'):
        return None, d.get('name') if d else None
    return d['klines'], d.get('name')

for code, mks in SYMS:
    got = False
    for mk in mks:
        try:
            kl, name = kline(code, mk)
            if kl and len(kl) >= 2:
                c1 = float(kl[-1].split(',')[2]); c0 = float(kl[-2].split(',')[2])
                pct = (c1 / c0 - 1) * 100
                d1 = kl[-1].split(',')[0]
                prev5 = None
                if len(kl) >= 4:
                    prev5 = (c1 / float(kl[0].split(',')[2]) - 1) * 100
                extra = f' 近{len(kl)}日累计{prev5:+.2f}%' if prev5 is not None else ''
                print(f'  {code}({name}, mk{mk}): {c1} {pct:+.2f}% [{d1}]{extra}')
                got = True
                break
        except Exception as e:
            print(f'  {code} mk{mk} FAIL {type(e).__name__}: {str(e)[:60]}')
    if not got:
        print(f'  {code}: 未获取')
    time.sleep(0.15)
