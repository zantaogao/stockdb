#!/usr/bin/env python3
# 复查：7 个带闸 prompt 去掉闸前缀后，应与 .bak 里的原 prompt 逐字相同
import json
old = {j['id'][:12]: (j.get('prompt') or '') for j in json.load(open('/Users/zantao/.hermes/cron/jobs.json.bak.20260925_calgate'))['jobs']}
new = {j['id'][:12]: (j.get('prompt') or '') for j in json.load(open('/Users/zantao/.hermes/cron/jobs.json'))['jobs']}
ok = 0
for i in ['ee38c4107fbe', 'd40477657377', '503e281adcfa', '6bcc281a869f', '897902eea54a', '603c3274e5ff', '30bee53b6e14']:
    full = new[i]
    o = old[i]
    if '交易日历硬闸' in full[:200]:
        stripped = full.split('\n', 1)[1]
    else:
        stripped = full
    same = (stripped == o)
    print(i, '原prompt完整' if same else f'⚠️有差异 旧长{len(o)} 新长{len(full)}')
    ok += same
print('完整:', ok, '/ 7')
