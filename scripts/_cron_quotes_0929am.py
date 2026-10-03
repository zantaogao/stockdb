#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0929早盘实时价：持仓+候选池。"""
import urllib.request

held = {'001238': '浙江正特', '003027': '同兴科技', '300837': '浙矿股份',
        '300970': '华绿生物', '301167': '建研设计', '603382': '海阳科技'}
cand = ['300640', '688096', '002554', '301512', '300971', '688348', '688051',
        '300935', '300837', '603488', '688793', '688671', '688391', '603778', '603185']


def sc(c):
    return ('sh' if c.startswith(('6', '68', '9')) else 'sz') + c


ks = sorted(set(list(held) + cand))
res = {}
for i in range(0, len(ks), 30):
    req = urllib.request.Request('https://hq.sinajs.cn/list=' + ','.join(sc(c) for c in ks[i:i + 30]),
                                 headers={'Referer': 'https://finance.sina.com.cn'})
    raw = urllib.request.urlopen(req, timeout=10).read().decode('gbk', 'ignore')
    for line in raw.strip().split('\n'):
        if 'hq_str_' not in line or '=""' in line:
            continue
        c = line.split('hq_str_')[1].split('=')[0][2:]
        p = line.split('"')[1].split(',')
        try:
            px, prev = float(p[3]), float(p[2])
            if px > 0 and prev > 0:
                res[c] = (px, prev, (px / prev - 1) * 100)
        except Exception:
            continue

print('== 持仓 ==')
for c, n in held.items():
    px, prev, ret = res.get(c, (0, 0, 0))
    print(f'{c} {n} 现价{px} 昨收{prev} 今日{ret:+.2f}%')
print('== 候选池 ==')
for c in cand:
    px, prev, ret = res.get(c, (0, 0, 0))
    print(f'{c} 现价{px} 昨收{prev} 今日{ret:+.2f}%')
