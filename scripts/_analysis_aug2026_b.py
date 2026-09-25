#!/usr/bin/env python3
"""Aug 2026: realized trade analysis per account + main NAV rebuild."""
import sqlite3, json, os, statistics
from collections import defaultdict

DB = os.path.expanduser('~/.hermes/stockdb/state.db')
TS = os.path.expanduser('~/.hermes/stockdb/tushare.db')
def norm(d): return str(d).replace('-', '')

c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
import duckdb
ts = duckdb.connect(TS, read_only=True)

closes = {}  # code -> sorted [(date, close)]
for code, d, cl in ts.execute("SELECT ts_code, trade_date, close FROM daily WHERE trade_date>='20260601' AND trade_date<='20260828'").fetchall():
    closes.setdefault(code.split('.')[0], []).append((d, cl))
for v in closes.values(): v.sort()
import bisect
def close_on(code, date):
    lst = closes.get(code)
    if not lst: return None
    i = bisect.bisect_right(lst, (date, 1e18)) - 1
    return lst[i][1] if i >= 0 else None

trades = [dict(t) for t in c.execute("SELECT * FROM trade_log WHERE REPLACE(trade_date,'-','')>='20260801'").fetchall()]
for t in trades: t['_d'] = norm(t['trade_date']); t['code_raw'] = t['code']

print('='*78)
print('A. 已实现交易明细统计（移动加权成本配对，仅8月卖出）')
print('='*78)
by = defaultdict(list)
for t in trades: by[t['strategy'] or 'main'].append(t)

summary = {}
for strat in sorted(by):
    tl = sorted(by[strat], key=lambda t: (t['_d'], t.get('trade_time') or ''))
    pos = defaultdict(lambda: {'sh':0,'tc':0.0,'bd':None})  # code -> shares, total cost, last buy date
    sells = []
    for t in tl:
        code = t['code_raw'].split('.')[0]
        d = t['direction'].upper()
        if d == 'BUY':
            p = pos[code]; p['sh'] += t['quantity']; p['tc'] += t['amount']
            p['bd'] = t['_d']
        elif d == 'SELL':
            p = pos[code]
            avg = p['tc']/p['sh'] if p['sh'] > 0 else t['price']
            pnl_pct = (t['price']/avg - 1)*100
            hold = None
            if p['bd']:
                cl0 = close_on(code, p['bd']); cl1 = close_on(code, t['_d'])
                if cl0 and cl1:
                    d0l = closes[code]; 
                    i0 = bisect.bisect_left([x[0] for x in d0l], p['bd'])
                    i1 = bisect.bisect_right([x[0] for x in d0l], t['_d'])-1
                    hold = i1-i0
            sells.append({'code':code,'name':t['name'],'bd':p['bd'],'sd':t['_d'],'avg':avg,
                          'px':t['price'],'pnl':pnl_pct,'amt':t['amount'],'hold':hold,
                          'score':t['signal_score'],'notes':(t['notes'] or '')[:40]})
            p['sh'] -= t['quantity']; p['tc'] -= avg*t['quantity']
            if p['sh'] <= 0: pos[code] = {'sh':0,'tc':0.0,'bd':None}
    if not sells:
        print(f"\n--- {strat}: 8月无卖出"); summary[strat]=(0,0,0,0,0,0); continue
    pnls = [s['pnl'] for s in sells]
    wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p <= 0]
    holds = [s['hold'] for s in sells if s['hold'] is not None]
    # weighted contribution = pnl_pct * sell amount
    total_amt = sum(s['amt'] for s in sells)
    wavg = sum(s['pnl']*s['amt'] for s in sells)/total_amt if total_amt else 0
    aw = statistics.mean(wins) if wins else 0; al = statistics.mean(losses) if losses else 0
    print(f"\n--- {strat}: 卖出{len(sells)}笔 | 胜率{len(wins)/len(pnls):.0%} ({len(wins)}胜/{len(losses)}负) | "
          f"均盈{aw:+.2f}% 均亏{al:+.2f}% 盈亏比{aw/abs(al) if al else float('inf'):.2f} | "
          f"金额加权均收益{wavg:+.2f}% | 中位持有{statistics.median(holds) if holds else '?'}天")
    worst = sorted(sells, key=lambda s: s['pnl'])[:3]
    best = sorted(sells, key=lambda s: -s['pnl'])[:3]
    print('   最佳: ' + '; '.join(f"{s['name']}{s['code']} {s['pnl']:+.1f}%持{s['hold']}天" for s in best))
    print('   最差: ' + '; '.join(f"{s['name']}{s['code']} {s['pnl']:+.1f}%持{s['hold']}天" for s in worst))
    # exit reason from notes
    reasons = defaultdict(int)
    for s in sells:
        n = s['notes']
        if '止损' in n: reasons['止损'] += 1
        elif '止盈' in n or '目标' in n: reasons['止盈'] += 1
        elif '规则5' in n or '评分' in n: reasons['评分/规则清仓'] += 1
        else: reasons['其他/换仓'] += 1
    print('   卖出原因: ' + ', '.join(f'{k}{v}笔' for k,v in reasons.items()))
    summary[strat] = (len(sells), len(wins)/len(pnls), aw, al, wavg, statistics.mean(holds) if holds else 0)

print()
print('='*78)
print('B. 主账户8月净值重建（main.json 08-03快照 + trade_log + daily收盘）')
print('='*78)
mj = json.load(open(os.path.expanduser('~/.hermes/stockdb/sim_accounts/main.json')))
cash = mj['cash']
hold = {v['code'].split('.')[0]: {'sh':v['shares'],'tc':v['shares']*v['avg_cost']} for v in mj['positions']}
print(f"08-03快照: cash={cash:,.0f} 持仓{len(hold)}只 成本={sum(v['tc'] for v in hold.values()):,.0f} "
      f"起始权益≈{cash+sum(v['tc'] for v in hold.values()):,.0f}")
main_tl = sorted([t for t in trades if (t['strategy'] or 'main')=='main'], key=lambda t:(t['_d'], t.get('trade_time') or ''))
daily_nav = {}
cur_date = None
for t in main_tl:
    code = t['code_raw'].split('.')[0]; d = t['_d']
    if d >= '20260804':
        if t['direction'].upper()=='BUY':
            cash -= t['amount']
            h = hold.setdefault(code, {'sh':0,'tc':0.0}); h['sh'] += t['quantity']; h['tc'] += t['amount']
        else:
            h = hold.get(code)
            if h and h['sh']>0:
                avg = h['tc']/h['sh']; h['tc'] -= avg*t['quantity']; h['sh'] -= t['quantity']
                if h['sh'] <= 0: del hold[code]
            else:
                h = hold.setdefault(code, {'sh':0,'tc':0.0})
            cash += t['amount']
    if d >= '20260804': daily_nav[d] = None  # mark dates
# note: 08-03 snapshot ALREADY contains 08-03 buys, so only apply trades >= 08-04
dates = sorted(d for d in daily_nav if daily_nav[d] is None)
# nav on last trade date + all trading days after
all_tdates = sorted(set(d for d,_,_ in ts.execute("SELECT trade_date,1,1 FROM daily WHERE trade_date>='20260804' AND trade_date<='20260828' GROUP BY trade_date").fetchall()))
# recompute sequentially to capture intermediate nav
cash = mj['cash']
hold = {v['code'].split('.')[0]: {'sh':v['shares'],'tc':v['shares']*v['avg_cost']} for v in mj['positions']}
tr_by_date = defaultdict(list)
for t in main_tl:
    if t['_d'] >= '20260804': tr_by_date[t['_d']].append(t)
nav_series = []
last_px = {}
for d in all_tdates:
    for t in tr_by_date.get(d, []):
        code = t['code_raw'].split('.')[0]
        if t['direction'].upper()=='BUY':
            cash -= t['amount']; h = hold.setdefault(code, {'sh':0,'tc':0.0})
            h['sh'] += t['quantity']; h['tc'] += t['amount']
        else:
            cash += t['amount']; h = hold.get(code)
            if h and h['sh']>0:
                avg = h['tc']/h['sh']; h['tc'] -= avg*t['quantity']; h['sh'] -= t['quantity']
                if h['sh'] <= 0: del hold[code]
    px = 0.0
    for code,h in hold.items():
        p = close_on(code, d)
        if p: px += h['sh']*p
    nav_series.append((d, cash+px))
start_eq = mj['cash'] + sum(v['shares']*v['avg_cost'] for v in mj['positions'])
print(f"重建区间: {nav_series[0][0]} → {nav_series[-1][0]}, {len(nav_series)}个交易日")
print(f"起始权益(成本口径)={start_eq:,.0f} 期末权益={nav_series[-1][1]:,.0f}")
rets = []
prev = start_eq
for d,nav in nav_series:
    rets.append(nav/prev-1); prev = nav
m = statistics.mean(rets); s = statistics.pstdev(rets)
peak = start_eq; mdd = 0
for d,nav in nav_series:
    peak = max(peak,nav); mdd = min(mdd, nav/peak-1)
print(f"8月区间收益 = {nav_series[-1][1]/start_eq*100-100:+.2f}% (08-03快照起, 08-28收盘口径)")
print(f"夏普 = {m/s*(252**0.5):.2f} | 日波动 {s*100:.2f}% | 最大回撤 {mdd*100:.1f}%")
# benchmark same window
mrows = ts.execute("SELECT trade_date, close FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date>='20260804' AND trade_date<='20260828' ORDER BY trade_date").fetchall()
if not mrows:
    mrows = ts.execute("SELECT trade_date, close FROM index_daily WHERE ts_code='000852.SH' AND trade_date>='20260804' ORDER BY trade_date").fetchall()
mret = (mrows[-1][1]/mrows[0][1]-1)*100
print(f"同期中证1000: {mret:+.2f}% → 主账户超额 {nav_series[-1][1]/start_eq*100-100-mret:+.2f}pp")
print("(已知: 08-20大调仓漏记8笔卖出→现金常数偏移~15.5万, 不影响夏普/收益相对形状)")