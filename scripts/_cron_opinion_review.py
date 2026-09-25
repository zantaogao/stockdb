#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cron 午间报告：上午意见复盘（首次提及价 vs 11:30 现价）— 只读"""
import sys, json, datetime, collections
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))
from core.prices import _fetch_sina

LOG = BASE / 'analysis' / 'opinion_log.jsonl'
TODAY = datetime.date.today().strftime('%Y-%m-%d')

rows = []
with open(LOG, encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if str(d.get('ts', '')).startswith(TODAY):
            rows.append(d)

first = {}
for d in rows:                      # 日志按时间顺序，先到先得
    k = d['key']
    if k not in first:
        first[k] = d

codes = sorted({d['code'] for d in rows})
q = _fetch_sina(codes)
px = {c: (v['price'] if v else None) for c, v in q.items()}

buckets = collections.defaultdict(list)
for k, d in first.items():
    kind = k.split('|')[0]
    cur = px.get(d['code'])
    if not cur:
        continue
    buckets[kind].append({
        'code': d['code'], 'ts': d['ts'][11:16], 'p0': d['price'], 'p1': cur,
        'chg': (cur / d['price'] - 1) * 100, 'text': d['text']})

label = {'sl': '🔴 破止损/建议卖出', 'nsl': '🟠 逼近止损', 'buyzone': '🟢 买入区',
         'stopbuy': '⛔ 停买区(较信号日-3%)', 'chase': '⚠️ 追高提示'}
for kind in ('sl', 'nsl', 'buyzone', 'stopbuy', 'chase'):
    arr = buckets.get(kind) or []
    if not arr:
        continue
    print('\n=== %s （%d 只，首次提及→11:30）===' % (label.get(kind, kind), len(arr)))
    for a in sorted(arr, key=lambda x: -x['chg']):
        print('  %s [%s] %.2f → %.2f  %+.2f%%   %s' % (a['code'], a['ts'], a['p0'], a['p1'], a['chg'], a['text'][:60]))
    if arr:
        print('  中位 %+.2f%%  均值 %+.2f%%  回正 %d/%d' % (
            sorted(x['chg'] for x in arr)[len(arr) // 2],
            sum(x['chg'] for x in arr) / len(arr),
            sum(1 for x in arr if x['chg'] > 0), len(arr)))
