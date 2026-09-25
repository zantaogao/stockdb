#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cron 午间报告：当日盘中意见按时间/类型汇总（只读）"""
import json, datetime, collections

LOG = '/Users/zantao/.hermes/stockdb/analysis/opinion_log.jsonl'
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

by_ts = collections.OrderedDict()
for d in rows:
    by_ts.setdefault(d['ts'], []).append(d)

print('今日记录 %d 条，%d 个时点' % (len(rows), len(by_ts)))
for ts, items in by_ts.items():
    kinds = collections.Counter(i['key'].split('|')[0] for i in items)
    print('\n=== %s  (%s) ===' % (ts, dict(kinds)))
    for i in items:
        print('  %s %s' % (i['icon'], i['text']))
