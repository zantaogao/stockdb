#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""午间(11:35)只读快照：主账户持仓实时价 vs 止盈/止损线 + 今日盘中意见聚合。不写库、不下单。"""
import sqlite3, os, json, urllib.request, collections

BASE = os.path.expanduser('~/.hermes/stockdb')
LED = os.path.join(BASE, 'ledger.db')


def sc(c):
    return ('sh' if c.startswith(('6', '68', '9')) else 'sz') + c


# ---------- 1) 持仓 ----------
con = sqlite3.connect('file:%s?mode=ro' % LED, uri=True)
rows = con.execute("SELECT code,name,avg_cost,shares,latest_price,target_price,stop_loss,buy_date FROM holdings WHERE status='hold'").fetchall()
con.close()

codes = [r[0] for r in rows]
q = {}
if codes:
    req = urllib.request.Request('https://hq.sinajs.cn/list=' + ','.join(sc(c) for c in codes),
                                 headers={'Referer': 'https://finance.sina.com.cn'})
    raw = urllib.request.urlopen(req, timeout=10).read().decode('gbk', 'ignore')
    for line in raw.strip().split('\n'):
        if 'hq_str_' not in line or '="";' in line or '=""' in line:
            continue
        code = line.split('hq_str_')[1].split('=')[0][2:]
        p = line.split('"')[1].split(',')
        if len(p) < 32:
            continue
        try:
            q[code] = {'open': float(p[1]), 'prev': float(p[2]), 'px': float(p[3]),
                       'high': float(p[4]), 'low': float(p[5]), 'amt': float(p[9])}
        except Exception:
            continue

print('=== 主账户持仓 半日实时(11:30) ===')
print('%-7s %-6s %7s %7s %7s %7s %7s  %7s  %s' % ('code', 'name', '成本', '昨收', '现价', '日内%', '持仓%', '盈亏额', '目标/止损距离'))
tot_pnl_before = 0.0
tot_pnl_now = 0.0
live_pnl = 0.0
mv = 0.0
for code, name, cost, sh, lp, tp, sl, bd in rows:
    v = q.get(code)
    if not v or v['px'] <= 0:
        print('%-7s %-6s 无实时数据(库内价 %.2f)' % (code, name[:6], lp or 0))
        continue
    px = v['px']
    intr = (px / v['prev'] - 1) * 100 if v['prev'] else 0
    posr = (px / cost - 1) * 100 if cost else 0
    pnl = (px - cost) * sh
    live_pnl += pnl
    mv += px * sh
    d_tp = (tp / px - 1) * 100 if tp else None
    d_sl = (sl / px - 1) * 100 if sl else None
    flag = ''
    if d_tp is not None and d_tp <= 1.5:
        flag = '⚠️近止盈'
    if d_sl is not None and d_sl >= -1.5:
        flag = '🛑近止损'
    print('%-7s %-6s %7.2f %7.2f %7.2f %+7.2f %+7.2f  %+8.0f  止盈%s/止损%s %s' % (
        code, name[:6], cost, v['prev'], px, intr, posr, pnl,
        ('%+.2f%%' % d_tp) if d_tp is not None else 'NA',
        ('%+.2f%%' % d_sl) if d_sl is not None else 'NA', flag))

print('\n持仓市值 %.0f 元  持仓浮动盈亏(对成本) %+.0f 元' % (mv, live_pnl))
print('现金 479446  总资产(实时估值参考) %.0f' % (mv + 479446))

# ---------- 2) 今日意见聚合 ----------
path = os.path.join(BASE, 'analysis', 'opinion_log.jsonl')
todays = []
for line in open(path, encoding='utf-8'):
    line = line.strip()
    if not line or '2026-09-16' not in line:
        continue
    try:
        d = json.loads(line)
    except Exception:
        continue
    ts = d.get('ts', '')
    if '2026-09-16' not in ts:
        continue
    todays.append(d)

print('\n=== 今日盘中意见 (09:00-11:30) 共 %d 条 ===' % len(todays))
cats = collections.Counter()
for d in todays:
    k = (d.get('key') or '').split('|')[0]
    cats[k] += 1
print('分类:', dict(cats))

# 按标的聚合（去重后每个标的最后状态）
last = {}
for d in todays:
    key = d.get('key') or ''
    kind = key.split('|')[0]
    code = d.get('code') or ''
    last[(code, kind)] = d

print('\n-- 盘中预警类（非buyzone）--')
for (code, kind), d in sorted(last.items(), key=lambda x: x[1]['ts']):
    if kind == 'buyzone':
        continue
    print('  %s %s %s %s' % (d['ts'][11:16], d.get('icon', ''), code, d.get('text', '')[:110]))

print('\n-- buyzone 唯一标的数: %d --' % len({c for (c, k) in last if k == 'buyzone'}))

# buyzone 标的的实盘表现
bz = {c for (c, k) in last if k == 'buyzone'}
if bz:
    req = urllib.request.Request('https://hq.sinajs.cn/list=' + ','.join(sc(c) for c in sorted(bz)),
                                 headers={'Referer': 'https://finance.sina.com.cn'})
    raw = urllib.request.urlopen(req, timeout=10).read().decode('gbk', 'ignore')
    perf = []
    for line in raw.strip().split('\n'):
        if 'hq_str_' not in line or '=""' in line:
            continue
        code = line.split('hq_str_')[1].split('=')[0][2:]
        p = line.split('"')[1].split(',')
        try:
            px, prev = float(p[3]), float(p[2])
            if px > 0 and prev > 0:
                perf.append(((px / prev - 1) * 100, code, px))
        except Exception:
            continue
    perf.sort(reverse=True)
    print('  buyzone 标的半日涨幅：均 %+.2f%%  中位 %+.2f%%  正 %d/%d' % (
        sum(x[0] for x in perf) / len(perf), sorted(x[0] for x in perf)[len(perf) // 2],
        sum(1 for x in perf if x[0] > 0), len(perf)))
    print('  最强:', ' '.join('%s%+.1f%%' % (c, r) for r, c, _ in perf[:8]))
    print('  最弱:', ' '.join('%s%+.1f%%' % (c, r) for r, c, _ in perf[-8:]))
