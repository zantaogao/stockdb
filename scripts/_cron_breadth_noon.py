#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cron 午间报告：全市场半日宽度快照（Sina 实时批量，只读，不下单/不写库）"""
import sys, json, urllib.request, time
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))

# 全市场代码表：用 signals.db 的 stock_basic（含 ts_code）+ tushare 兜底
import duckdb
codes = []
con = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
try:
    rows = con.execute("SELECT ts_code FROM stock_basic WHERE list_status='L'").fetchall()
except Exception:
    rows = con.execute('SELECT ts_code FROM stock_basic').fetchall()
for (ts,) in rows:
    c = str(ts).split('.')[0]
    if len(c) == 6 and c.isdigit():
        codes.append(c)
con.close()
codes = sorted(set(codes))
print('股票池 %d 只' % len(codes))


def sina_code(c):
    return ('sh' if c.startswith(('6', '68', '9')) else 'sz') + c


def fetch(chunk):
    sc = ','.join(sina_code(c) for c in chunk)
    req = urllib.request.Request('https://hq.sinajs.cn/list=' + sc,
                                 headers={'Referer': 'https://finance.sina.com.cn'})
    raw = urllib.request.urlopen(req, timeout=8).read().decode('gbk', 'ignore')
    out = {}
    for line in raw.strip().split('\n'):
        if 'hq_str_' not in line or '=""' in line:
            continue
        try:
            scode = line.split('hq_str_')[1].split('=')[0]
            parts = line.split('"')[1].split(',')
            if len(parts) < 10:
                continue
            c = scode[2:]
            px = float(parts[3] or 0)
            prev = float(parts[2] or 0)
            op = float(parts[1] or 0)
            amt = float(parts[9] or 0)   # 成交额(元)
            if px > 0 and prev > 0:
                out[c] = {'px': px, 'prev': prev, 'open': op, 'amt': amt}
        except Exception:
            continue
    return out


quotes = {}
CH = 500
t0 = time.time()
for i in range(0, len(codes), CH):
    chunk = codes[i:i + CH]
    for attempt in range(2):
        try:
            d = fetch(chunk)
            quotes.update(d)
            break
        except Exception as e:
            if attempt == 1:
                print('chunk %d err %s' % (i, e))
            time.sleep(0.3)
print('取到行情 %d 只，耗时 %.1fs' % (len(quotes), time.time() - t0))

up = dn = flat = 0
up5 = dn5 = 0
zt = dt = 0
amt_total = 0.0
op_up = op_dn = 0
up_codes = []
for c, q in quotes.items():
    r = (q['px'] / q['prev'] - 1) * 100
    o = (q['open'] / q['prev'] - 1) * 100 if q['open'] else 0
    amt_total += q['amt']
    if o > 0:
        op_up += 1
    elif o < 0:
        op_dn += 1
    if r > 0.05:
        up += 1
    elif r < -0.05:
        dn += 1
    else:
        flat += 1
    if r > 5:
        up5 += 1
    if r < -5:
        dn5 += 1
    lim = 19.8 if c.startswith(('30', '68')) else 9.8
    if r >= lim:
        zt += 1
    if r <= -lim:
        dt += 1
    if r > 5:
        up_codes.append((round(r, 2), c))

tot = up + dn + flat
print('\n=== 半日宽度（截至 11:30 收盘价）===')
print('  样本 %d 只：涨 %d / 平 %d / 跌 %d （涨占比 %.1f%%）' % (tot, up, flat, dn, up / tot * 100))
print('  高开 %d / 低开 %d（%d%% 低开）' % (op_up, op_dn, op_dn / tot * 100))
print('  强(>5%%) %d 只 / 弱(<-5%%) %d 只' % (up5, dn5))
print('  涨停(近) %d / 跌停(近) %d' % (zt, dt))
print('  全市场成交额 %.0f 亿元（半日）' % (amt_total / 1e8))
up_codes.sort(reverse=True)
print('  涨幅榜前15:', ' '.join('%s%+.1f%%' % (c, r) for r, c in up_codes[:15]))
print('\n  中位涨幅 %.2f%%' % sorted((q['px'] / q['prev'] - 1) * 100 for q in quotes.values())[len(quotes) // 2])

# 指数当日
from core.prices import _fetch_sina
idx = {'000001': '上证', '399001': '深成', '399006': '创业板', '000852': '中证1000'}
d = _fetch_sina(list(idx.keys()))
print('\n=== 指数 11:30 ===')
for c, n in idx.items():
    v = d.get(c)
    if v:
        print('  %-8s %.2f  %+.2f%%  开%+.2f%%' % (n, v['price'], (v['price'] / v['prev'] - 1) * 100,
                                                  (v['open'] / v['prev'] - 1) * 100 if v['open'] else 0))
