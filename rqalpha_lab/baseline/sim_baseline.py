# -*- coding: utf-8 -*-
"""执行实验室 基线臂 v0：v8 引擎 + 现行生产卖法（含 5B/5C），账本可配对比较的地基。
血统：scripts/_cron_prod_vs_v8_full_0927.py（0927 三臂，OPS_FACTS 记载的 prod_vs_v8_v3 数即出于此）。
基线纪律（10-03 定案，见 OPS_FACTS「执行实验室 603257 验收」）：
  - 只做**同口径相对比较**（规则 A vs B，同 fill/同数据/同随机性），绝对收益不作数；
  - 判据 = 配对日收益差 + NW-t(lag5)，池均值差单看不算；
  - fill 口径 v0 = 决策日 close（与 0927 三臂同，先复现再谈改）；
    fill=开盘 口径列为第一个 A/B 候选（B1），顺带量 fill 口径敏感度。
臂：A_prod  = 生产融合分 fo(0.375*20d+0.625*40d) + 生产卖法（现行规则映射版）
    B_v8    = v8 融合分 f8(0.25*10d+0.75*40d) + 生产卖法   （=0927 B 臂，现行生产配置）
    B1_v8_open = B_v8 但成交价改次日均价近似（次日 VWAP=amount/vol，adj 同口径）——fill 敏感度
产物：nav_<arm>.csv（日 nav/ret）、trades_<arm>.csv、summary.json（含配对 NW-t）。
"""
import numpy as np, pandas as pd, lightgbm as lgb, duckdb, json
from pathlib import Path

B = Path('/Users/zantao/.hermes/stockdb/analysis/retrain_20260927_v8')
OUT = Path(__file__).parent
COST = 0.0015
START = '20250304'          # 与 0927 三臂同窗（v8 样本可用起点）
END = '20260930'

con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
cal = [str(r[0]).replace('-', '') for r in
       con.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
ci = {x: i for i, x in enumerate(cal)}
imap = {str(t).replace('-', ''): float(c) for t, c in
        con.execute("SELECT date,close FROM index_daily WHERE index_code='000852'").fetchall()}

def ts_of(c):
    return c+'.SH' if c.startswith(('6', '68')) else (c+'.BJ' if c.startswith('9') else c+'.SZ')

# ── 预测分数（v8 三模型对样本内历史打分，与 0927 完全同法）──
P = {}
for k in ['10d', '20d', '40d']:
    m = lgb.Booster(model_str=(B / f'lgb_reg_{k}_v8.txt').read_text())
    d = pd.read_parquet(B / f'samples_{k}.parquet'); nf = m.num_feature()
    sub = d[d.date >= START]
    P[k] = pd.DataFrame({'date': sub.date.values, 'code': sub.code.values,
                         'p_' + k: m.predict(sub.iloc[:, 2:2+nf].values)})
v8 = P['10d'].merge(P['20d'], on=['date', 'code']).merge(P['40d'], on=['date', 'code'])
v8['f8'] = 0.25*v8.p_10d + 0.75*v8.p_40d
v8['fo'] = 0.375*v8.p_20d + 0.625*v8.p_40d

dates = sorted(d for d in v8.date.unique() if ci.get(d) is not None and d <= END)
codes = sorted(v8.code.unique()); idx = {c: i for i, c in enumerate(codes)}; di = {d: i for i, d in enumerate(dates)}
dil = ",".join(f"'{d}'" for d in dates); allts = ",".join(f"'{ts_of(c)}'" for c in codes)

PX = np.full((len(dates), len(codes)), np.nan)       # 收盘价（复权）
OP = np.full_like(PX, np.nan)                        # 开盘价（复权）
VW = np.full_like(PX, np.nan)                        # 日均价 amount/vol（复权）
adj = {(str(t), str(d)): float(f) for t, d, f in
       con.execute("SELECT ts_code, trade_date, adj_factor FROM adj_factor").fetchall()}
for t_, d_, c_, o_, vol_, amt_ in con.execute(
        f"SELECT ts_code,trade_date,close,open,vol,amount FROM daily "
        f"WHERE ts_code IN ({allts}) AND trade_date IN ({dil})").fetchall():
    j = idx.get(str(t_)[:6]); i = di.get(str(d_))
    if j is None or i is None: continue
    # 价一律 bfq 未复权（与 0927 三臂同法；样本模型预测目标同为 bfq 口径）
    PX[i, j] = float(c_); OP[i, j] = float(o_)
    # 日均价：tushare daily 口径 vol=手 amount=千元 → vwap = amount*1000/(vol*100) = amount*10/vol
    VW[i, j] = (float(amt_)*10/float(vol_)) if vol_ and float(vol_) > 0 else float(c_)
PXC = np.full_like(PX, np.nan)
for i in range(1, len(dates)):
    ok = ~np.isnan(PX[i-1]) & ~np.isnan(PX[i]) & (PX[i-1] > 0)
    PXC[i, ok] = PX[i, ok]/PX[i-1, ok] - 1
LIM = np.where(np.array([c.startswith(('30', '68')) for c in codes]), 0.197, 0.097)

def mkmat(col):
    M = np.full((len(dates), len(codes)), np.nan)
    for r in v8.itertuples():
        i = di.get(r.date)
        if i is not None: M[i, idx[r.code]] = getattr(r, col)
    return M
M8 = mkmat('f8'); Mo = mkmat('fo')

def pctmat(M):
    O = np.full_like(M, np.nan)
    for i in range(len(M)):
        row = M[i]; ok = ~np.isnan(row)
        if ok.sum() > 100: O[i, ok] = (pd.Series(row[ok]).rank(pct=True)*100).values
    return O
P8 = pctmat(M8); Po = pctmat(Mo)

halved = np.full(len(dates), False)
for i, d_ in enumerate(dates):
    if d_ in imap and ci[d_] > 0 and cal[ci[d_]-1] in imap:
        halved[i] = imap[d_]/imap[cal[ci[d_]-1]] - 1 <= -0.02

def simulate(Pct, M, br, sr, fill):
    """fill: 'close'=决策日收盘成交（0927 三臂口径，基准）
             'next_open'=决策次日开盘成交（贴近实盘：分数收盘出、exec_agent 次日 09:3x 成交）"""
    hd = np.zeros(len(codes), int); cost = np.full(len(codes), np.nan)
    act = np.zeros(len(codes), bool); alloc = np.zeros(len(codes))
    cash = 1.0; navs = []; trades = []
    pend_s = []; pend_b = []; pend_s_why = {}; pend_b_amt = {}
    for i, d_ in enumerate(dates):
        # 1) 执行昨日挂单（next_open 口径：今日开盘价成交，缺开盘价退回今日收盘）
        for j in pend_s:
            if not act[j]: continue
            sp = OP[i, j] if not np.isnan(OP[i, j]) else PX[i, j]
            pnl = sp/cost[j]-1
            cash += alloc[j]*(sp/cost[j])*(1-COST)
            trades.append((d_, codes[j], pend_s_why.pop(j, '?'), pnl, hd[j], sp))
            act[j] = False; alloc[j] = 0
        pend_s.clear()
        for j in pend_b:
            if act[j]: continue
            bp = OP[i, j] if not np.isnan(OP[i, j]) else PX[i, j]
            act[j] = True; cost[j] = bp; hd[j] = 0; alloc[j] = pend_b_amt.pop(j, 0.0)
            cash -= alloc[j]
        pend_b.clear()
        # 2) 收盘决策
        for j in np.where(act)[0]:
            if hd[j] == 0: continue
            p = PX[i, j]
            if np.isnan(p): p = PX[i-1, j] if i > 0 and not np.isnan(PX[i-1, j]) else cost[j]
            pnl = p/cost[j]-1
            a, why = sr(j, i, pnl, Pct, M, hd)
            if a:
                if fill == 'close':
                    cash += alloc[j]*(p/cost[j])*(1-COST)
                    trades.append((d_, codes[j], why, pnl, hd[j], p))
                    act[j] = False; alloc[j] = 0
                else:
                    pend_s.append(j); pend_s_why[j] = why
        slots = 20-act.sum()-len(pend_b)
        if slots > 0 and i > 0:
            cand = np.where((~act) & (~np.isnan(PX[i])))[0]
            order = cand[np.argsort(-Pct[i, cand])]
            for j in order:
                if act[j] or j in pend_b or slots <= 0: continue
                if np.isnan(PXC[i, j]) or PXC[i, j] >= LIM[j]: continue
                if not br(j, i, Pct, M): continue
                per = (cash - sum(pend_b_amt.values()))/slots*(0.5 if halved[i] else 1.0)
                if fill == 'close':
                    act[j] = True; cost[j] = PX[i, j]; hd[j] = 0; alloc[j] = per; cash -= per
                else:
                    pend_b.append(j); pend_b_amt[j] = per
                slots -= 1
        hd[act] += 1
        mv = sum(alloc[j]*(PX[i, j]/cost[j] if not np.isnan(PX[i, j]) and cost[j] > 0 else 1.0)
                 for j in np.where(act)[0])
        navs.append((d_, cash+mv+0.0, int(act.sum())))
    nav = pd.DataFrame(navs, columns=['date', 'nav', 'npos']); nav['ret'] = nav.nav.pct_change()
    return nav, pd.DataFrame(trades, columns=['date', 'code', 'reason', 'pnl', 'held', 'fill_px'])

# ── 现行生产规则映射（与 0927 sell_prod 一致；规则参数见 intraday_decision.py 头）──
def sell_prod(j, i, pnl, Pct, M, hd):
    if pnl <= -0.12: return True, 'stop'
    if Pct[i, j] < 30 and pnl < 0: return True, 'score_neg'
    if hd[j] >= 20 and Pct[i, j] < 30 and pnl < 0.08: return True, '5B'
    if hd[j] >= 30 and M[i, j] < np.nanmean(M[i]): return True, '5C'
    return False, None
def buy_prod(j, i, Pct, M): return Pct[i, j] >= 90
def buy_v8(j, i, Pct, M):
    n = max((~np.isnan(M[i])).sum(), 1)
    return Pct[i, j] >= 100-20*100/n

ARMS = [
    ('A_prod',      Mo, Po, buy_prod, sell_prod, 'close'),
    ('B_v8',        M8, P8, buy_v8,  sell_prod, 'close'),
    ('B1_v8_nextopen', M8, P8, buy_v8, sell_prod, 'next_open'),
]

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

# 配对日收益差 + NW-t（相对基线 A_prod）：两 nav 日期集合相同（同一 dates），取交集对齐，无差日=0
summary = {}
navs = {}
for label, M, Pct, br, sr, fill in ARMS:
    nav, tr = simulate(Pct, M, br, sr, fill)
    nav.to_csv(OUT / f'nav_{label}.csv', index=False)
    tr.to_csv(OUT / f'trades_{label}.csv', index=False)
    nav['year'] = nav.date.str[:4]
    per_year = {}
    for y, g in nav.groupby('year'):
        g = g.dropna(subset=['ret'])
        ann = (g.nav.iloc[-1]/g.nav.iloc[0])**(244/len(g))-1
        shp = g.ret.mean()/g.ret.std()*np.sqrt(244) if g.ret.std() > 0 else 0
        dd = (g.nav/g.nav.cummax()-1).min()*100
        per_year[y] = dict(ann=round(ann*100, 1), sharpe=round(shp, 2), maxdd=round(dd, 1))
    summary[label] = dict(fill=fill, years=per_year, n_trades=len(tr),
        win=round(float((tr.pnl > 0).mean())*100) if len(tr) else None,
        avg_hold=round(float(tr.held.mean()), 1) if len(tr) else None,
        reasons=tr.reason.value_counts().to_dict() if len(tr) else {})
    navs[label] = nav.set_index('date')['ret']
    print(f'{label} done: {per_year}', flush=True)

pairs = {}
base = navs['A_prod']
for label in ['B_v8', 'B1_v8_nextopen']:
    common = base.index.intersection(navs[label].index)
    d = (navs[label].loc[common] - base.loc[common]).values
    pairs[label + '_vs_A'] = dict(mean_daily_bps=round(float(np.nanmean(d))*1e4, 1),
                                  nw_t5=round(float(nw_t(d)), 2), n_days=int(len(d)))
summary['paired'] = pairs
(OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1))
print('PAIRED:', json.dumps(pairs, ensure_ascii=False))
