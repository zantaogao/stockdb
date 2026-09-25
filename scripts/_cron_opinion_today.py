#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cron 午间报告：抽取当日盘中意见记录（只读）"""
import json, sys, datetime

LOG = '/Users/zantao/.hermes/stockdb/analysis/opinion_log.jsonl'
STATE = '/Users/zantao/.hermes/stockdb/analysis/opinion_state.json'
TODAY = datetime.date.today().strftime('%Y-%m-%d')

rows = []
keys = {}
with open(LOG, encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        for k in d.keys():
            keys[k] = keys.get(k, 0) + 1
        rows.append(d)

print('总记录数:', len(rows))
print('字段统计:', json.dumps(keys, ensure_ascii=False))

today = []
for d in rows:
    blob = json.dumps(d, ensure_ascii=False)
    if TODAY in blob:
        today.append(d)

print('今日记录数:', len(today))
for d in today:
    print('-' * 60)
    print(json.dumps(d, ensure_ascii=False)[:1500])

print('=' * 60)
print('最近 12 条（任意日期，看格式）:')
for d in rows[-12:]:
    print(json.dumps(d, ensure_ascii=False)[:800])

print('=' * 60)
try:
    with open(STATE, encoding='utf-8') as f:
        st = json.load(f)
    print('opinion_state.json:')
    print(json.dumps(st, ensure_ascii=False, indent=1)[:4000])
except Exception as e:
    print('state read err', e)
