# -*- coding: utf-8 -*-
"""5B 规则 A/B（10-03，执行实验室第二刀）：B_v8_5bon(锚,现行5B在) vs B_v8_5boff(只关5B)。
5B（08-18 拍板阈值8%）：持仓≥20交易日 且 融合分位<30 且 pnl<8% → 超期低分横盘卖。
引擎/数据与 ab_5c.py 逐行同法（血统 _cron_prod_vs_v8_full_0927.py）。
判据：规则事件研究（反事实+5/10/20d）优先，账户配对 NW-t(lag5) 辅证。"""
import numpy as np, pandas as pd, lightgbm as lgb, duckdb, json
from pathlib import Path

B = Path('/Users/zantao/.hermes/stockdb/analysis/retrain_20260927_v8')
OUT = Path(__file__).parent
COST = 0.0015
START, END = '20250304', '20260930'

con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
cal = [str(r[0]).replace('-', '') for r in
       con.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
ci = {x: i for i, x in enumerate(cal)}
imap = {str(t).replace('-', ''): float(c) for t, c in
        con.execute("SELECT date,close FROM index_daily WHERE index_code='000852'").fetchall()}

def ts_of(c):
    return c+'.SH' if c.startswith(('6', '68')) else (c+'.BJ' if c.startswith('9') else c+'.SZ')

P = {}
for k in ['10d', '20d', '40d']:
    m = lgb.Booster(model_str=(B / f'lgb_reg_{k}_v8.txt').read_text())
    d = pd.read_parquet(B / f'samples_{k}.parquet'); nf = m.num_feature()
    sub = d[d.date >= START]
    P[k] = pd.DataFrame({'date': sub.date.values, 'code': sub.code.values,
                         'p_' + k: m.predict(sub.iloc[:, 2:2+nf].values)})
v8 = P['10d'].merge(P['20d'], on=['date', 'code']).merge(P['40d'], on=['date', 'code'])
v8['f8'] = 0.25*v8.p_10d + 0.75*v8.p_40d

dates = sorted(d for d in v8.date.unique() if ci.get(d) is not None and d <= END)
codes = sorted(v8.code.unique()); idx = {c: i for i, c in enumerate(codes)}; di = {d: i for i, d in enumerate(dates)}
dil = ",".join(f"'{d}'" for d in dates); allts = ",".join(f"'{ts_of(c)}'" for c in codes)

PX = np.full((len(dates), len(codes)), np.nan)
for t_, d_, c_ in con.execute(
        f"SELECT ts_code,trade_date,close FROM daily "
        f"WHERE ts_code IN ({allts}) AND trade_date IN ({dil})").fetchall():
    j = idx.get(str(t_)[:6]); i = di.get(str(d_))
    if j is not None and i is not None: PX[i, j] = float(c_)
PXC = np.full_like(PX, np.nan)
for i in range(1, len(dates)):
    ok = ~np.isnan(PX[i-1]) & ~np.isnan(PX[i]) & (PX[i-1] > 0)
    PXC[i, ok] = PX[i, ok]/PX[i-1, ok] - 1
LIM = np.where(np.array([c.startswith(('30', '68')) for c in codes]), 0.197, 0.097)

M8 = np.full((len(dates), len(codes)), np.nan)
for r in v8.itertuples():
    i = di.get(r.date)
    if i is not None: M8[i, idx[r.code]] = r.f8

def pctmat(M):
    O = np.full_like(M, np.nan)
    for i in range(len(M)):
        row = M[i]; ok = ~np.isnan(row)
        if ok.sum() > 100: O[i, ok] = (pd.Series(row[ok]).rank(pct=True)*100).values
    return O
P8 = pctmat(M8)

halved = np.full(len(dates), False)
for i, d_ in enumerate(dates):
    if d_ in imap and ci[d_] > 0 and cal[ci[d_]-1] in imap:
        halved[i] = imap[d_]/imap[cal[ci[d_]-1]] - 1 <= -0.02

def simulate(Pct, M, br, sr):
    hd = np.zeros(len(codes), int); cost = np.full(len(codes), np.nan)
    act = np.zeros(len(codes), bool); alloc = np.zeros(len(codes))
    cash = 1.0; navs = []; trades = []
    for i, d_ in enumerate(dates):
        for j in np.where(act)[0]:
            if hd[j] == 0: continue
            p = PX[i, j]
            if np.isnan(p): p = PX[i-1, j] if i > 0 and not np.isnan(PX[i-1, j]) else cost[j]
            pnl = p/cost[j]-1
            a, why = sr(j, i, pnl, Pct, M, hd)
            if a:
                cash += alloc[j]*(p/cost[j])*(1-COST)
                trades.append((d_, codes[j], why, pnl, hd[j], i, j, cost[j]))
                act[j] = False; alloc[j] = 0
        slots = 20-act.sum()
        if slots > 0 and i > 0:
            cand = np.where((~act) & (~np.isnan(PX[i])))[0]
            order = cand[np.argsort(-Pct[i, cand])]
            for j in order:
                if act[j] or slots <= 0: continue
                if np.isnan(PXC[i, j]) or PXC[i, j] >= LIM[j]: continue
                if not br(j, i, Pct, M): continue
                per = cash/slots*(0.5 if halved[i] else 1.0)
                act[j] = True; cost[j] = PX[i, j]; hd[j] = 0; alloc[j] = per; cash -= per; slots -= 1
        hd[act] += 1
        mv = sum(alloc[j]*(PX[i, j]/cost[j] if not np.isnan(PX[i, j]) and cost[j] > 0 else 1.0)
                 for j in np.where(act)[0])
        navs.append((d_, cash+mv, int(act.sum())))
    nav = pd.DataFrame(navs, columns=['date', 'nav', 'npos']); nav['ret'] = nav.nav.pct_change()
    return nav, pd.DataFrame(trades, columns=['date', 'code', 'reason', 'pnl', 'held', 'di', 'cj', 'cost'])

def sell_with_5b(j, i, pnl, Pct, M, hd, use5b=True):
    if pnl <= -0.12: return True, 'stop'
    if Pct[i, j] < 30 and pnl < 0: return True, 'score_neg'
    if use5b and hd[j] >= 20 and Pct[i, j] < 30 and pnl < 0.08: return True, '5B'
    if hd[j] >= 30 and M[i, j] < np.nanmean(M[i]): return True, '5C'
    return False, None
def buy_v8(j, i, Pct, M):
    n = max((~np.isnan(M[i])).sum(), 1)
    return Pct[i, j] >= 100-20*100/n

def nw_t(x, lag=5):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    n = len(x)
    if n < lag+2: return np.nan
    m = x.mean(); e = x-m
    S = (e*e).sum()/n
    for l in range(1, lag+1):
        w = 1-l/(lag+1)
        S += 2*w*(e[:-l]*e[l:]).sum()/n
    se = np.sqrt(S/n)
    return m/se if se > 0 else np.nan

ARMS = {'B_v8_5bon': True, 'B_v8_5boff': False}
navs, trs = {}, {}
for label, use5b in ARMS.items():
    nav, tr = simulate(P8, M8, buy_v8,
                       lambda j, i, pnl, Pct, M, hd, u=use5b: sell_with_5b(j, i, pnl, Pct, M, hd, u))
    navs[label] = nav.set_index('date')['ret']; trs[label] = tr
    nav[['date', 'nav', 'npos']].to_csv(OUT / f'nav_{label}.csv', index=False)
    tr.drop(columns=['di', 'cj', 'cost']).to_csv(OUT / f'trades_{label}.csv', index=False)
    nav['year'] = nav.date.str[:4]
    py = {}
    for y, g in nav.groupby('year'):
        g = g.dropna(subset=['ret'])
        py[y] = dict(ann=round(((g.nav.iloc[-1]/g.nav.iloc[0])**(244/len(g))-1)*100, 1),
                     sharpe=round(g.ret.mean()/g.ret.std()*np.sqrt(244), 2) if g.ret.std() > 0 else 0,
                     maxdd=round((g.nav/g.nav.cummax()-1).min()*100, 1))
    print(f'{label}: {py} 笔数{len(tr)} 胜率{(tr.pnl>0).mean()*100:.0f}% 均持{tr.held.mean():.0f}d {dict(tr.reason.value_counts())}', flush=True)

common = navs['B_v8_5bon'].index.intersection(navs['B_v8_5boff'].index)
d = (navs['B_v8_5boff'].loc[common] - navs['B_v8_5bon'].loc[common]).values
pair = dict(off_minus_on_bps=round(float(np.nanmean(d))*1e4, 1), nw_t5=round(float(nw_t(d)), 2), n_days=int(len(d)))
print('PAIRED 5boff-5bon:', json.dumps(pair), flush=True)

nav_a = navs['B_v8_5bon']; nav_b = navs['B_v8_5boff']
by_year = {}
for y in sorted(set(s[:4] for s in common)):
    c = [s for s in common if s.startswith(y)]
    dy = (nav_b.loc[c]-nav_a.loc[c]).values
    by_year[y] = dict(bps=round(float(np.nanmean(dy))*1e4, 1), t=round(float(nw_t(dy)), 2), n=len(c))
print('BY_YEAR:', json.dumps(by_year), flush=True)

# 事件研究：锚臂每个 5B 卖点，若没卖，+5/10/20 交易日后收盘 vs 卖价
t5 = trs['B_v8_5bon']; t5 = t5[t5.reason == '5B']
rows = []
for r in t5.itertuples():
    i, j = r.di, r.cj
    fut = {}
    for hz in (5, 10, 20):
        k = i + hz
        if k < len(dates) and not np.isnan(PX[k, j]) and not np.isnan(PX[i, j]):
            fut[f'f{hz}'] = PX[k, j]/PX[i, j] - 1
    rows.append(dict(date=r.date, code=r.code, pnl_at_sell=round(r.pnl, 4), held=int(r.held),
                     **{k: round(v, 4) for k, v in fut.items()}))
cf = pd.DataFrame(rows)
cf.to_csv(OUT / 'counterfactual_5b_sells.csv', index=False)
stat = {}
for hz in (5, 10, 20):
    col = cf.get(f'f{hz}')
    if col is not None and col.notna().sum() >= 5:
        v = col.dropna().values
        stat[f'+{hz}d'] = dict(n=len(v), mean_pct=round(float(v.mean())*100, 2),
                               median_pct=round(float(np.median(v))*100, 2),
                               win_pct=round(float((v > 0).mean())*100), t=round(float(nw_t(v, lag=0)), 2))
# 分年（5B 卖点 2025/2026 分布 + 分年反事实均值）
cf['year'] = cf.date.astype(str).str[:4]
byyr = {y: dict(n=int(len(g)),
                f20_mean=round(float(g.f20.dropna().mean())*100, 2) if g.f20.notna().sum() >= 5 else None)
        for y, g in cf.groupby('year')}
print('COUNTERFACTUAL(卖后继续持有收益):', json.dumps(stat, ensure_ascii=False), flush=True)
print('CF_BY_YEAR:', json.dumps(byyr), flush=True)

(OUT / 'ab_5b_summary.json').write_text(json.dumps(
    dict(paired=pair, by_year=by_year, counterfactual=stat, cf_by_year=byyr,
         n_5b_trades=int((trs['B_v8_5bon'].reason == '5B').sum()),
         window=[dates[0], dates[-1]]), ensure_ascii=False, indent=1))
print('done', flush=True)
