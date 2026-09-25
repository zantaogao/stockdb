#!/usr/bin/env python3
"""August 2026 signal quality + trading performance analysis (one-off)."""
import sqlite3, json, os, statistics
from collections import defaultdict

DB = os.path.expanduser('~/.hermes/stockdb/state.db')
TS = os.path.expanduser('~/.hermes/stockdb/tushare.db')

def norm(d): return d.replace('-', '')

c = sqlite3.connect(DB); c.row_factory = sqlite3.Row

print('='*70)
print('PART 1: ic_window (w10) — 8月各信号源 10日预测IC 与 Top10前向收益%')
print('='*70)
cols = ['ic_fusion_w10','ic_reg10_w10','ic_3f_w10','ic_cmmr_w10','ic_cmmrf_w10','ic_center_w10','ic_dual_w10']
names = {'ic_fusion_w10':'三模型融合','ic_reg10_w10':'reg10','ic_3f_w10':'三因子','ic_cmmr_w10':'CMMR','ic_cmmrf_w10':'CMMR+','ic_center_w10':'中枢','ic_dual_w10':'双信号'}
topcols = {'ic_fusion_w10':'fwd10_top_main','ic_3f_w10':'fwd10_top_3f','ic_cmmr_w10':'fwd10_top_cmmr','ic_cmmrf_w10':'fwd10_top_cmmrf','ic_center_w10':'fwd10_top_center','ic_dual_w10':'fwd10_top_dual'}
rows = c.execute("SELECT * FROM ic_window WHERE signal_date>='20260801' AND signal_date<='20260831' ORDER BY signal_date").fetchall()
hdr = 'date      n     ' + ''.join(f'{names[k][:6]:>8}' for k in cols) + '   | ' + ''.join(f'{names[k][:6]+"Top10":>10}' for k in cols if k in topcols)
print(hdr)
sums = defaultdict(list); tops = defaultdict(list)
for r in rows:
    line = f"{r['signal_date']} {int(r['n']):>5} " + ''.join(f"{r[k] if r[k] is not None else float('nan'):>8.3f}" for k in cols)
    def g(k):
        try: return r[topcols[k]]
        except (IndexError, KeyError): return None
    line += '   | ' + ''.join(f"{(g(k) if g(k) is not None else float('nan')):>10.2f}" for k in cols if k in topcols)
    print(line)
    for k in cols:
        if r[k] is not None: sums[k].append(r[k])
    for k in topcols:
        if g(k) is not None: tops[k].append(r[topcols[k]])
print('-'*len(hdr))
line = 'MEAN          ' + ''.join(f"{statistics.mean(sums[k]):>8.3f}" if sums[k] else f'{"":>8}' for k in cols)
line += '   | ' + ''.join(f"{statistics.mean(tops[k]):>10.2f}" if tops[k] else f'{"":>10}' for k in cols if k in topcols)
print(line)
line = 'WIN(IC>0)     ' + ''.join(f"{sum(1 for v in sums[k] if v>0)/len(sums[k]):>7.0%} " if sums[k] else f'{"":>8}' for k in cols)
print(line)

# market benchmark for Aug from daily (中证1000 idx? use index_daily_raw or 000852)
print()
print('='*70)
print('PART 2: 策略账户 8月净值表现 (strategy_accounts表)')
print('='*70)
import duckdb
ts = duckdb.connect(TS, read_only=True)
mrows = ts.execute("SELECT trade_date, close FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date>='20260801' AND trade_date<='20260831' ORDER BY trade_date").fetchall()
if not mrows:
    mrows = ts.execute("SELECT trade_date, close FROM index_daily WHERE ts_code='000852.SH' AND trade_date>='20260801' ORDER BY trade_date").fetchall()
mkt = {norm(d): v for d, v in mrows}
mkeys = sorted(mkt)
if mkeys:
    mret = (mkt[mkeys[-1]]/mkt[mkeys[0]]-1)*100
    print(f'中证1000 8月({mkeys[0]}→{mkeys[-1]}): {mret:+.2f}%')
mkt_daily = {}
for i in range(1, len(mkeys)):
    mkt_daily[mkeys[i]] = (mkt[mkeys[i]]/mkt[mkeys[i-1]]-1)*100

try:
    meta = {r['account_id']: r for r in c.execute("SELECT * FROM strategy_accounts_meta").fetchall()}
except sqlite3.OperationalError:
    # M2 仍为 JSON 存储：meta 从 sim_accounts/*.json 读
    import json, glob, os
    meta = {}
    for p in glob.glob(os.path.expanduser('~/.hermes/stockdb/sim_accounts/*.json')):
        j = json.load(open(p))
        aid = os.path.basename(p)[:-5]
        if aid == 'main': continue
        meta[aid] = {'account_id': aid, 'name': j.get('name', aid),
                     'initial_capital': j.get('initial_capital', 1000000)}
    meta = {k: dict(v) for k, v in meta.items()}
for aid, m in sorted(meta.items()):
    navs = c.execute("SELECT date,nav,cash,pos_value,daily_ret,market_ret,n_pos FROM strategy_accounts WHERE account_id=? AND date>='2026-08-01' ORDER BY date", (aid,)).fetchall()
    navs2 = c.execute("SELECT date,nav,cash,pos_value,daily_ret,market_ret,n_pos FROM strategy_accounts WHERE account_id=? AND date>='20260801' ORDER BY date", (aid,)).fetchall()
    navs = list(navs)+list(navs2)
    if not navs:
        print(f"{aid:16s} {m['name']}: 无8月NAV记录")
        continue
    start_nav, end_nav = navs[0]['nav'], navs[-1]['nav']
    init = m['initial_capital']
    ret_from_start = (end_nav/init-1)*100
    ret_aug = (end_nav/start_nav-1)*100 if start_nav else 0
    rets = [r['daily_ret'] for r in navs if r['daily_ret'] is not None]
    sharpe = (statistics.mean(rets)/statistics.pstdev(rets)*(252**0.5)) if len(rets)>2 and statistics.pstdev(rets)>0 else float('nan')
    # max drawdown from nav series
    peak = navs[0]['nav']; mdd = 0
    for r in navs:
        peak = max(peak, r['nav']); mdd = min(mdd, r['nav']/peak-1)
    # market over same period
    mret_same = 0
    d0, d1 = norm(navs[0]['date']), norm(navs[-1]['date'])
    dd = [d for d in mkeys if d0 <= d <= d1]
    if len(dd) >= 2:
        mret_same = (mkt[dd[-1]]/mkt[dd[0]]-1)*100
    try:
        pos = c.execute("SELECT COUNT(*) FROM strategy_positions WHERE account_id=?", (aid,)).fetchone()[0]
    except sqlite3.OperationalError:
        import json as _json, glob as _glob, os as _os
        _p = _os.path.expanduser(f'~/.hermes/stockdb/sim_accounts/{aid}.json')
        try: pos = len(_json.load(open(_p)).get('positions', []))
        except Exception: pos = -1
    print(f"{aid:16s} {m['name']}: {len(navs)}天 | 8月区间{ret_aug:+6.2f}% | 累计{ret_from_start:+6.2f}% | 同期中证1000 {mret_same:+6.2f}% | 超额{ret_aug-mret_same:+6.2f}pp | 夏普{sharpe:5.2f} | 最大回撤{mdd*100:5.1f}% | 当前持仓{pos}")

print()
print('='*70)
print('PART 3: 8月已实现交易 (trade_log, 按账户)')
print('='*70)
trades = c.execute("SELECT * FROM trade_log WHERE REPLACE(trade_date,'-','')>='20260801' AND REPLACE(trade_date,'-','')<='20260831'").fetchall()
print('trade_log columns:', [d[1] for d in c.execute("PRAGMA table_info(trade_log)").fetchall()])
if trades:
    by = defaultdict(list)
    for t in trades:
        d = dict(t); d['_d'] = norm(d['trade_date'])
        by[d.get('strategy') or 'main'].append(d)
    for strat in sorted(by):
        tl = by[strat]
        buys = [t for t in tl if (t.get('direction') or '').upper()=='BUY']
        sells = [t for t in tl if (t.get('direction') or '').upper()=='SELL']
        pnls = [t['pnl_pct'] for t in sells if t.get('pnl_pct') is not None]
        pnl_amts = [t['pnl'] for t in sells if t.get('pnl') is not None]
        line = f"{strat:16s} 买{len(buys):3d}笔/卖{len(sells):3d}笔"
        if pnls:
            wins = [p for p in pnls if p>0]; losses = [p for p in pnls if p<=0]
            aw = statistics.mean(wins) if wins else 0
            al = statistics.mean(losses) if losses else 0
            plr = (aw/abs(al)) if al else float('inf')
            line += f" | 已结算{len(pnls)}笔 胜率{len(wins)/len(pnls):.0%} 均盈{aw:+.2f}% 均亏{al:+.2f}% 盈亏比{plr:.2f} 累计收益和{sum(pnls):+.1f}pp"
        if pnl_amts:
            line += f" | 盈亏金额合计 {sum(pnl_amts):+,.0f}元"
        line += f" | 买入金额{sum(t.get('amount') or 0 for t in buys):,.0f}"
        print(line)

print()
print('='*70)
print('PART 4: 主账户8月净值重建 (main.json 08-03快照 + trade_log)')
print('='*70)
mj = json.load(open(os.path.expanduser('~/.hermes/stockdb/sim_accounts/main.json')))
print('main.json keys:', list(mj.keys()))