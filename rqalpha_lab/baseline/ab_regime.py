# -*- coding: utf-8 -*-
"""制度闸门 A/B（10-19 立项）：生产选品链路已有中证1000 MA20 斜率闸门（斜率<0 跳过选股），
但实验室锚臂 B_v8 模拟时没有（sim_baseline.py 无 regime 逻辑）→ 实验室与生产行为不一致，本实验补洞。
四臂（同 fill=决策日 close、同数据、同窗 20250304~20260930、费 0.15%）：
  A0_repro    = B_v8 现行配置零改动（锚点复现，nav 必须与 nav_B_v8.csv 逐位一致 maxdiff=0.0）
  A1_ma20slope= 中证1000 close/MA20-1 斜率 ≤0 当日禁新开仓（已有持仓卖出照常，不强清）
  A2_ma50     = close < MA50 禁新开仓（不强清）
  A3_slope10  = close/MA20-1 斜率 ≤ -1% 才禁买（更松变体）
MA 只用当日及以前数据（决策在收盘，无未来函数）。
引擎与 ab_5c.py/sim_baseline.py 逐行同法（血统 _cron_prod_vs_v8_full_0927.py）。
判据：配对日收益差 NW-t(lag5)，|t|<2 证据不足；必须分年拆（2025 vs 2026）。
ONLY_A0=1 只跑 A0 复现锚点，省算力。
产物：nav_<arm>.csv（含 cash 列）/ trades_<arm>.csv / ab_regime_summary.json / run_regime.log / AB_REGIME.md。
"""
import os, numpy as np, pandas as pd, lightgbm as lgb, duckdb, json
from pathlib import Path

B = Path('/Users/zantao/.hermes/stockdb/analysis/retrain_20260927_v8')
OUT = Path(__file__).parent
COST = 0.0015
START, END = '20250304', '20260930'
ONLY_A0 = os.environ.get('ONLY_A0') == '1'

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

# ── 制度闸门序列（中证1000，MA 只用当日及以前，无未来函数）──
# 索引轴 = index_daily 自己的交易日序列（含 START 之前历史，MA50 可满窗）
ix_dates = sorted(imap)
ix_pos = {d: k for k, d in enumerate(ix_dates)}
ix_close = np.array([imap[d] for d in ix_dates])
cs = np.cumsum(np.nan_to_num(ix_close))
def ma(k, win):
    """k 位置（含）往前 win 根收盘均值；不足 win 根返回 nan"""
    if k + 1 < win: return np.nan
    return (cs[k] - (cs[k-win] if k >= win else 0.0)) / win
missing = [d for d in dates if d not in ix_pos]
print(f'gate: index series {ix_dates[0]}~{ix_dates[-1]} n={len(ix_dates)}, sim-window dates missing from index: {len(missing)}', flush=True)
gate_A1 = np.zeros(len(dates), bool)   # slope20 <= 0 禁买
gate_A2 = np.zeros(len(dates), bool)   # close < MA50 禁买
gate_A3 = np.zeros(len(dates), bool)   # slope20 <= -1% 禁买
for i, d_ in enumerate(dates):
    k = ix_pos.get(d_)
    if k is None: continue
    m20, m50 = ma(k, 20), ma(k, 50)
    slope20 = ix_close[k]/m20 - 1 if not np.isnan(m20) else np.nan
    gate_A1[i] = bool(slope20 <= 0) if not np.isnan(slope20) else False
    gate_A2[i] = bool(ix_close[k] < m50) if not np.isnan(m50) else False
    gate_A3[i] = bool(slope20 <= -0.01) if not np.isnan(slope20) else False

def simulate(Pct, M, br, sr, gate):
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
        if slots > 0 and i > 0 and not gate[i]:
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
        navs.append((d_, cash+mv, int(act.sum()), cash))
    nav = pd.DataFrame(navs, columns=['date', 'nav', 'npos', 'cash']); nav['ret'] = nav.nav.pct_change()
    return nav, pd.DataFrame(trades, columns=['date', 'code', 'reason', 'pnl', 'held', 'di', 'cj', 'cost'])

def sell_prod(j, i, pnl, Pct, M, hd):
    if pnl <= -0.12: return True, 'stop'
    if Pct[i, j] < 30 and pnl < 0: return True, 'score_neg'
    if hd[j] >= 20 and Pct[i, j] < 30 and pnl < 0.08: return True, '5B'
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

def paired_t(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    if len(x) < 3: return np.nan
    sd = x.std(ddof=1)
    return x.mean()/(sd/np.sqrt(len(x))) if sd > 0 else np.nan

ARMS = {
    'A0_repro':     np.zeros(len(dates), bool),
    'A1_ma20slope': gate_A1,
    'A2_ma50':      gate_A2,
    'A3_slope10':   gate_A3,
}
if ONLY_A0: ARMS = {'A0_repro': ARMS['A0_repro']}
navs, trs, stats = {}, {}, {}
for label, gate in ARMS.items():
    nav, tr = simulate(P8, M8, buy_v8, sell_prod, gate)
    navs[label] = nav.set_index('date')['ret']; trs[label] = tr
    nav[['date', 'nav', 'npos', 'cash']].to_csv(OUT / f'nav_{label}.csv', index=False)
    tr.drop(columns=['di', 'cj', 'cost']).to_csv(OUT / f'trades_{label}.csv', index=False)
    g = nav.dropna(subset=['ret'])
    ann = (g.nav.iloc[-1]/g.nav.iloc[0])**(244/len(g))-1
    mdd = (g.nav/g.nav.cummax()-1).min()
    cash_pct = float(np.clip(g.cash/g.nav, 0.0, 1.0).mean())
    blocked = int(gate[[di[d] for d in g.date]].sum())
    nav['year'] = nav.date.str[:4]
    py = {}
    for y, gg in nav.groupby('year'):
        gg = gg.dropna(subset=['ret'])
        py[y] = dict(ann=round(((gg.nav.iloc[-1]/gg.nav.iloc[0])**(244/len(gg))-1)*100, 1),
                     sharpe=round(gg.ret.mean()/gg.ret.std()*np.sqrt(244), 2) if gg.ret.std() > 0 else 0,
                     maxdd=round((gg.nav/gg.nav.cummax()-1).min()*100, 1))
    stats[label] = dict(annualized_pct=round(ann*100, 1), mdd_pct=round(mdd*100, 1),
                        cash_pct_avg=round(cash_pct*100, 1), blocked_days=blocked,
                        n_days=len(g), years=py, n_trades=len(tr),
                        win=round(float((tr.pnl > 0).mean())*100) if len(tr) else None,
                        avg_hold=round(float(tr.held.mean()), 1) if len(tr) else None,
                        reasons=tr.reason.value_counts().to_dict() if len(tr) else {})
    print(f"{label}: {py} ann={stats[label]['annualized_pct']}% mdd={stats[label]['mdd_pct']}% "
          f"cash={stats[label]['cash_pct_avg']}% gate_days={blocked} 笔数{len(tr)} "
          f"胜率{stats[label]['win']}% 均持{stats[label]['avg_hold']}d", flush=True)

# A0 复现校验（对既有锚点 nav_B_v8.csv 逐位）
ref = pd.read_csv(OUT / 'nav_B_v8.csv', dtype={'date': str})
a0 = navs['A0_repro'] if False else pd.read_csv(OUT / 'nav_A0_repro.csv', dtype={'date': str})
ref_nav = ref.set_index('date')['nav']
a0_nav = a0.set_index('date')['nav']
assert list(ref_nav.index) == list(a0_nav.index), 'A0 date index differs from anchor'
maxdiff = float(np.abs(a0_nav.values - ref_nav.values).max())
print(f'REPRO maxdiff vs nav_B_v8.csv = {maxdiff}', flush=True)
if maxdiff != 0.0:
    (OUT / 'ab_regime_summary.json').write_text(json.dumps(
        dict(status='repro_failed', repro_maxdiff=maxdiff), ensure_ascii=False, indent=1))
    raise SystemExit('REPRO FAILED — 环境漂移，停止')

if ONLY_A0:
    print('ONLY_A0 done (repro ok)', flush=True)
    raise SystemExit(0)

# 配对 vs A0：全段 + 分年
base = navs['A0_repro']
paired = {}
for label in ['A1_ma20slope', 'A2_ma50', 'A3_slope10']:
    common = base.index.intersection(navs[label].index)
    d = (navs[label].loc[common] - base.loc[common]).values
    seg = {}
    for y in sorted(set(s[:4] for s in common)):
        c = [s for s in common if s.startswith(y)]
        dy = (navs[label].loc[c]-base.loc[c]).values
        seg[y] = dict(diff_pp=round(float(np.nanmean(dy))*244*100, 2),
                      bps=round(float(np.nanmean(dy))*1e4, 1),
                      t=round(float(nw_t(dy)), 2), n=len(c))
    paired[label + '_vs_A0'] = dict(
        mean_daily_bps=round(float(np.nanmean(d))*1e4, 1),
        ann_diff_pp=round(float(np.nanmean(d))*244*100, 2),
        paired_t=round(float(paired_t(d)), 2),
        nw_t5=round(float(nw_t(d)), 2), n_days=int(len(d)),
        seg_2025_diff_pp=seg.get('2025', {}).get('diff_pp'),
        seg_2026_diff_pp=seg.get('2026', {}).get('diff_pp'),
        seg=seg)
    print('PAIRED', label, json.dumps(paired[label + '_vs_A0'], ensure_ascii=False), flush=True)

out = dict(status='ok', repro_maxdiff=maxdiff, window=[dates[0], dates[-1]],
           gate_days=dict(A1=int(gate_A1.sum()), A2=int(gate_A2.sum()), A3=int(gate_A3.sum())),
           arms=stats, paired=paired)
(OUT / 'ab_regime_summary.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
print('SUMMARY written', flush=True)
