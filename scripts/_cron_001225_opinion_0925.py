#!/usr/bin/env python3
# 001225 假跌票是否真进了意见链（0925 意见日志 + 当前关注池 + 今晨决策日志）
import json, sqlite3, os, time
BASE = '/Users/zantao/.hermes/stockdb'

u = json.load(open(BASE + '/analysis/opinion_universe.json'))
uni = u.get('universe', {})
print('universe 大小:', len(uni), '| 001225 在其中:', '001225' in uni, '| signal_date:', u.get('signal_date'), '| generated:', u.get('generated_at'))

hits = [l for l in open(BASE + '/analysis/opinion_log.jsonl') if '2026-09-25' in l and '001225' in l]
print('今日意见日志 001225 条数:', len(hits))
for h in hits[-3:]:
    r = json.loads(h)
    print('  ', r.get('time', r.get('ts')), r.get('icon', ''), str(r.get('text', r.get('msg', '')))[:150])

d = open(BASE + '/DECISIONS.md', encoding='utf-8').read()
seg = [ln for ln in d.splitlines() if '001225' in ln or '和泰' in ln]
print('DECISIONS.md 001225 相关行:', len(seg))
for s in seg[-2:]:
    print('  ', s[:200])
