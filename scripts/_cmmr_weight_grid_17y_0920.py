# -*- coding: utf-8 -*-
"""CMMR 权重全网格 17年重放回测（2026-09-20）
动机：09-20 权重对拍只有31个信号日；本回测在 tushare.db 上逐日重放全市场打分，
打分口径与生产 cmmr_standalone.py 逐字复刻（slope>0.02→满档, 0<s≤0.02→半档;
pct10<-8%→满档, -8~-4%→半档; vr<0.8 或 (vr>1.2且收阳)→满档; slope<0→0分红线）。
每套权重 w=(趋势,超卖,量能)：归一分>=0.8 入池（复刻生产80分线），
池内 (分降, pct10升=回调最深) 取前10 —— 与 _cmmr_exit_rules_17y 选池代理一致。
信号日收盘打分，次日收盘入场，持有10个交易日，成本0.1%/边。
超额 = top10组合收益 − 当日全可交易域中位收益（同日同进出，配对）。
NW-t lag=10（重叠窗口）。分年超额单列，不让平均掩盖年份。
网格：w1+w2+w3=100 步长10（66组）+ 手动候选。
"""
import duckdb, sqlite3, os, sys, time
import numpy as np, pandas as pd

HOME = os.path.expanduser('~')
DB = f'{HOME}/.hermes/stockdb/tushare.db'
SIG = f'{HOME}/.hermes/stockdb/signals.db'
START = sys.argv[1] if len(sys.argv) > 1 else '20090101'
FWD = 10  # 持有交易日
COST = 0.002  # 双边

t0 = time.time()
con = duckdb.connect(DB, read_only=True)
bad = set()
sc = sqlite3.connect(f'file:{SIG}?mode=ro', uri=True)
for code, nm, mk in sc.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(code).startswith(('8','4','92')):
        bad.add(str(code))
print(f'ST/退市/北交所剔除: {len(bad)}', flush=True)

df = con.execute(f"""
  SELECT d.ts_code, CAST(d.trade_date AS INT) AS td, d."open", d.close, d.vol, a.adj_factor
  FROM daily d LEFT JOIN adj_factor a USING (ts_code, trade_date)
  WHERE d.trade_date >= '{START}'
""").df()
print('rows:', len(df), f'{time.time()-t0:.0f}s', flush=True)
df = df[~df.ts_code.str[:6].isin(bad)]
col_order = sorted(df.ts_code.unique())
def piv(col):
    return df.pivot(index='td', columns='ts_code', values=col).reindex(columns=col_order).astype('float32')
close = piv('close'); opn = piv('open'); vol = piv('vol')
adjf = piv('adj_factor').ffill().fillna(1.0)
A = close * adjf              # 复权收盘
A_ff = A.ffill().values       # 停牌期间用前值（只在持仓期内缺价时使用）
cal = list(close.index)
print('cal:', len(cal), cal[0], '->', cal[-1], flush=True)

# ---- 因子矩阵（与生产逐字同口径， rolling含当日） ----
ma40 = close.rolling(40).mean()
ma40_prev = close.rolling(20).mean().shift(40)
slope = ((ma40 - ma40_prev) / ma40_prev).values
p10 = (close / close.shift(10) - 1).values
vr = (vol / vol.rolling(5).mean()).values
enough = close.rolling(60).count().values >= 60
S = slope; P = p10; R = vr
O = opn.values; C = close.values

T = np.where(S > 0.02, 1.0, np.where(S > 0, 0.5, 0.0)).astype('float32')
Ov = np.where(P < -0.08, 1.0, np.where(P < -0.04, 0.5, 0.0)).astype('float32')
V = np.where((R < 0.8) | ((R > 1.2) & (C > O)), 1.0, 0.0).astype('float32')
# 红线：slope<0 → 全分归0
kill = (S < 0) | ~enough | np.isnan(C)
T[kill] = 0; Ov[kill] = 0; V[kill] = 0

# 入场可交易：信号日次日 raw close 存在；退出日 i+1+FWD 在日历内
n_days = len(cal)
vi = np.array([i for i in range(60, n_days - FWD - 1) if bool(enough[i].any())])
print('有效信号日:', len(vi), cal[vi[0]], '->', cal[vi[-1]], flush=True)

# 全可交易域 fwd（同一进出日）：entry=A_ff[i+1]非nan, exit=A_ff[i+1+FWD]
ent = np.full((n_days, len(col_order)), np.nan, 'float32')
ext = np.full_like(ent, np.nan)
for i in vi:
    e = A_ff[i+1]
    ent[i] = np.where(np.isnan(C[i+1]), np.nan, e)  # 次日停牌无raw价=不可入场
    ext[i] = A_ff[i+1+FWD]
fwd_all = ext/ent - 1
uni_fwd = np.nanmedian(fwd_all, axis=1)  # 全市场中位（基准，不含成本，配对对等）
print('矩阵就绪', f'{time.time()-t0:.0f}s', flush=True)

WEIGHTS = {}
for w1 in range(0, 101, 10):
    for w2 in range(0, 101 - w1, 10):
        WEIGHTS[f'{w1}/{w2}/{100-w1-w2}'] = (w1, w2, 100-w1-w2)
for extra in [(40,40,20),(40,20,40),(50,30,20),(50,20,30),(30,40,30),(25,50,25),(60,20,20),(20,30,50),(33,34,33)]:
    WEIGHTS['H'+'/'.join(map(str,extra))] = extra

def nw_t(v, lag=10):
    v = np.asarray(v); n = len(v)
    if n < 10: return 0.0
    m = v.mean(); e = v - m
    g = sum(np.cov(e[j:], e[:-j], ddof=1)[0,1]*(1-j/(lag+1)) for j in range(1, lag+1))
    return m / np.sqrt((np.var(v, ddof=1) + 2*g)/n)

years = np.array([d//100 for d in cal])
rows = []
for name, w in WEIGHTS.items():
    wt, wo, wv = w
    tot = wt + wo + wv
    if tot == 0: continue
    sc_all = (wt*T + wo*Ov + wv*V) / tot
    ex = np.zeros(len(vi)); yrs = np.zeros(len(vi), int); pooln = np.zeros(len(vi), int)
    k = 0
    for i in vi:
        srow = sc_all[i]
        pool_idx = np.where(srow >= 0.8)[0]
        pooln[k] = len(pool_idx)
        if len(pool_idx) < 10:
            ex[k] = np.nan; yrs[k] = years[i]; k += 1; continue
        ps = srow[pool_idx]; pp = P[i, pool_idx]; pf = fwd_all[i, pool_idx]
        ok = ~np.isnan(pf)
        ps, pp, pf = ps[ok], pp[ok], pf[ok]
        if len(ps) < 10:
            ex[k] = np.nan; yrs[k] = years[i]; k += 1; continue
        order = np.lexsort((pp, -ps))[:10]  # 分降、pct10升（回调最深）
        ex[k] = pf[order].mean() - uni_fwd[i] - COST
        yrs[k] = years[i]; k += 1
    keepm = ~np.isnan(ex)
    ex = ex[keepm]; yrs = yrs[keepm]
    t_ = nw_t(ex*100)
    yr_mean = {int(y): round(float(ex[yrs == y].mean()*100), 2) for y in sorted(set(yrs)) if (yrs == y).sum() > 30}
    pos_years = sum(1 for v_ in yr_mean.values() if v_ > 0); n_years = len(yr_mean)
    rows.append(dict(w=name, days=len(ex), pool_mean=round(float(pooln[pooln>0].mean())),
                     ex_pp=round(float(ex.mean()*100), 4), nw_t=round(float(t_), 2),
                     win=round(float((ex>0).mean()), 3), pos_yr=f'{pos_years}/{n_years}',
                     years=yr_mean))
res = pd.DataFrame(rows).sort_values('nw_t', ascending=False)
res.drop(columns=['years']).to_csv(f'{HOME}/.hermes/stockdb/analysis/cmmr_weight_grid_17y_0920.csv', index=False)
pd.set_option('display.width', 250)
print(res.drop(columns=['years']).head(20).to_string(index=False))
print('\n=== 关键组 ===')
for k_ in ['40/40/20','40/20/40','20/40/40','30/40/30','50/30/20','50/20/30','25/50/25']:
    sub = res[res.w == k_]
    if len(sub):
        r = sub.iloc[0]
        print(f"{k_:<12} 池均{r.pool_mean} 日均超{r.ex_pp:+.3f}pp NW-t {r.nw_t:+.2f} 胜率{r.win:.0%} 正年{r.pos_yr}  分年: {r.years}")
print('\nTop5 分年:')
for _, r in res.head(5).iterrows():
    print(f"{r.w:<12} NW-t {r.nw_t:+.2f}  分年: {r.years}")
print(f'\n总耗时 {time.time()-t0:.0f}s')
