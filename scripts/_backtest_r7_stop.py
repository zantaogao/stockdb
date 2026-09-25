#!/usr/bin/env python3
"""Backtest hypothetical floating-loss stop (R7) for strategy accounts, Aug 2026.
For each SELL in Aug with pnl<0: reconstruct buy avg cost from trade_log, walk daily
closes between buy and sell; if close ever <= cost*(1-x), assume exit at that level.
Compare mean loss / total loss for x in {4,5,6,8}% vs actual.
"""
import sqlite3, duckdb, os, statistics
from collections import defaultdict
import bisect

DB = os.path.expanduser('~/.hermes/stockdb/state.db')
TS = os.path.expanduser('~/.hermes/stockdb/tushare.db')
def norm(d): return str(d).replace('-','')

c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
ts = duckdb.connect(TS, read_only=True)

closes = {}
for code, d, cl in ts.execute("SELECT ts_code, trade_date, close FROM daily WHERE trade_date>='20260701' AND trade_date<='20260828'").fetchall():
    closes.setdefault(code.split('.')[0], []).append((d, cl))
for v in closes.values(): v.sort()

trades = [dict(t) for t in c.execute("SELECT * FROM trade_log WHERE strategy IS NOT NULL AND strategy != 'main' AND strategy != ''").fetchall()]
for t in trades: t['_d'] = norm(t['trade_date'])

by = defaultdict(list)
for t in trades: by[(t['strategy'], t['code'].split('.')[0])].append(t)

def daily_between(code, d0, d1):
    lst = closes.get(code, [])
    ds = [x[0] for x in lst]
    i0 = bisect.bisect_left(ds, d0); i1 = bisect.bisect_right(ds, d1)
    return lst[i0:i1]

print('R7 浮亏止损回测（8月已实现亏损单，策略账户）')
print(f"{'阈值':>4} | {'被砍单数':>6} | {'新均亏':>7} | {'旧均亏':>7} | {'亏损和变化':>9}")
results = {}
sells_info = []
for (strat, code), tl in by.items():
    tl.sort(key=lambda t: (t['_d'], t.get('trade_time') or ''))
    sh = 0; tc = 0.0; bd = None
    for t in tl:
        if t['direction'].upper() == 'BUY':
            sh += t['quantity']; tc += t['amount']
            if bd is None: bd = t['_d']
        else:
            if sh <= 0: continue
            avg = tc/sh
            pnl = (t['price']/avg-1)*100
            sells_info.append(dict(strat=strat, code=code, bd=bd, sd=t['_d'], avg=avg,
                                   px=t['price'], pnl=pnl, amt=t['amount']))
            sh -= t['quantity']; tc -= avg*t['quantity']
            if sh <= 0: sh=0; tc=0.0; bd=None

aug_sells = [s for s in sells_info if '20260801' <= s['sd'] <= '20260831']
losses = [s for s in aug_sells if s['pnl'] < 0]
base_mean = statistics.mean(s['pnl'] for s in losses)
base_sum = sum(s['pnl']*s['amt'] for s in losses)/sum(s['amt'] for s in losses)
for x in (4,5,6,8):
    cut = 0; new_pnls = []
    for s in losses:
        path = daily_between(s['code'], norm(s['bd'])+'a', s['sd'])
        path = [(d,cl) for d,cl in path if d > s['bd'] and d <= s['sd']]
        stop_px = s['avg']*(1-x/100)
        hit = next((cl for d,cl in path if cl <= stop_px), None)
        if hit is not None and hit < s['px']:  # stop would have exited earlier at higher... 
            # exit price = approx stop level (assume fill near stop_px*.. use close that breached)
            new_pnls.append((hit/s['avg']-1)*100); cut += 1
        elif hit is not None:
            new_pnls.append((hit/s['avg']-1)*100); cut += 1
        else:
            new_pnls.append(s['pnl'])
    nm = statistics.mean(new_pnls)
    print(f" -{x}%  |   {cut:3d}   | {nm:+6.2f}% | {base_mean:+6.2f}% | 加权 {base_sum:+.1f} -> ", end='')
    ws = sum(p*a for p,a in zip(new_pnls,[s['amt'] for s in losses]))/sum(s['amt'] for s in losses)
    print(f"{ws:+.1f}pp")
# distribution of actual loss depths
depths = []
for s in losses:
    path = daily_between(s['code'], s['bd'], s['sd'])
    path = [(d,cl) for d,cl in path if d > s['bd'] and d <= s['sd']]
    if path:
        mn = min(cl for _,cl in path)
        depths.append((s['strat'],s['code'],s['pnl'],(mn/s['avg']-1)*100))
print(f"\n亏损单最大浮亏分布（{len(depths)}笔）:")
worst = sorted(depths, key=lambda x: x[2]-x[3])[:0]
import collections
buckets = collections.Counter()
for st,code,fin,mx in depths:
    b = min(int(-mx//3*3),21) if mx<0 else 0
    buckets[b]+=1
for b in sorted(buckets): print(f"  最大浮亏 {b}~{b+3}%: {buckets[b]}笔")
# also count how many losses were <5% all along (stop wouldn't touch)
shallow = sum(1 for st,c_,f,mx in depths if mx > -4)
print(f"全程浮亏未超-4%（R7不触碰）: {shallow}/{len(depths)}")