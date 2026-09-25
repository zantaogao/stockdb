#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""午间指定标的实时(只读)：条件票 + 榜单前票 + 主账户关注票。"""
import urllib.request

codes = {
    '603186': '华正新材(10d独立,连涨7)', '002491': '通鼎互联(10d独立)', '688503': '聚和材料(10d独立)',
    '600076': '康欣新材(融合第1)', '600785': '新华百货(10d)', '300328': '宜安科技(10d)',
    '001326': '联域股份(中枢Top10)', '300970': '华绿生物(CMMR)', '002942': '新农股份(CMMR)',
    '603409': '汇通控股(Agent)', '688607': '康众科技(Agent)', '688021': '奥福科技(Agent已卖)',
    '603811': '诚意药业(Agent已卖)', '300274': '阳光电源(Agent已卖)', '301557': '常友科技(主账户已卖)',
    '601615': '明阳智能(主账户)', '001332': '锡装股份(主账户)', '688191': '智洋创新(主账户)',
    '002454': '松芝股份(主账户)', '301110': '青木科技(主账户)', '605598': '上海港湾(主账户)',
    '301283': '聚胶股份(主账户)', '301237': '和顺科技(主账户)', '688636': '智明达(主账户)',
    '600609': '金杯汽车(已卖)', '300427': '红相股份(已卖)', '300176': '鸿特科技(已卖)',
}


def sc(c):
    return ('sh' if c.startswith(('6', '68', '9')) else 'sz') + c


ks = list(codes)
out = []
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
            px, prev, op = float(p[3]), float(p[2]), float(p[1])
            if px > 0 and prev > 0:
                out.append(((px / prev - 1) * 100, c, px, prev, (op / prev - 1) * 100 if op else 0))
        except Exception:
            continue
out.sort(reverse=True)
print('=== 午间实时（含今日卖出/买入票）===')
for chg, c, px, prev, op in out:
    print('  %s %-22s %8.2f  %+6.2f%%  (昨收%.2f 开%+.2f%%)' % (c, codes[c], px, chg, prev, op))
