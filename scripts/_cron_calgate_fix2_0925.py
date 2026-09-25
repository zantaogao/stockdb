#!/usr/bin/env python3
"""补漏：盘后综合报告(ee38c4107fbe) + Agent全权盘中决策(897902eea54a) 加日历硬闸。
与 _cron_prompt_calgate_0925.py 同闸文；已带闸的任务跳过，防重复。"""
import json
from pathlib import Path

P = Path('/Users/zantao/....hermes/cron/jobs.json')
P = Path('/Users/zantao/.hermes/cron/jobs.json')
data = json.loads(P.read_text())
CHECK = '/usr/bin/python3 -B /Users/zantao/.hermes/stockdb/scripts/_cron_tradecal_check.py'
GATE = ('⚠️交易日历硬闸（2026-09-25 调休休市误交易事故）：先跑 ' + CHECK +
        '（输出 TRADING_DAY=1 或 0）。=0（节假日/周末休市）→ 最终回复只写一行'
        '「今日休市，无报告」，禁止数据采集、禁止写任何文件、禁止推QQ。=1 才继续。\n')
TARGETS = {'ee38c4107fbe', '897902eea54a'}
hit = []
for j in data['jobs']:
    if j.get('id', '')[:12] in TARGETS:
        pr = j.get('prompt') or ''
        if '交易日历硬闸' in pr:
            print(j['id'][:12], '已带闸，跳过')
            continue
        j['prompt'] = GATE + pr
        hit.append((j['id'][:12], j.get('name', '')))
tmp = P.with_suffix('.json.tmp')
tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
tmp.replace(P)
print('补闸:', hit)
