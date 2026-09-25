# -*- coding: utf-8 -*-
"""独立交叉验证 2024：逐字生产公式(ma40.shift(20)分母) + float64 + np.lexsort 重算逐日ex，对比 CSV
打分逐字复刻 cmmr_standalone：trend/oversold/vol 三腿原始档位分(不做kill清零)，
score=三腿和，最后仅 ma40_slope<0 → score=0。"""
import duckdb, sqlite3, os
import numpy as np, pandas as pd
HOME = os.path.expanduser('~')
con = duckdb.connect(f'{HOME}/.hermes/stockdb/tushare.db', read_only=True)
sc = sqlite3.connect(f'file:{HOME}/.hermes/stockdb/signals.db?mode=ro', uri=True)
bad = set()
for code, nm, mk in sc.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(code).startswith(('8','4','92')):
        bad.add(str(code))
sc.close()
df = con.execute("""
  SELECT d.ts_code, CAST(d.trade_date AS INT) td, d."open", d.close, d.vol, a.adj_factor
  FROM daily d LEFT JOIN adj_factor a USING (ts_code, trade_date)
  WHERE d.trade_date BETWEEN '20230801' AND '20250131'
""").df()
con.close()
df = df[~df.ts_code.str[:6].isin(bad)]
col_order = sorted(df.ts_code.unique())
def piv(c): return df.pivot(index='td', columns='ts_code', values=c).reindex(columns=col_order)
close = piv('close'); opn = piv('open'); vol = piv('vol')
adjf = piv('adj_factor').ffill().fillna(1.0)
A = (close*adjf).ffill().values
C = close.values; O = opn.values
cal = np.array(close.index)
ma40 = close.rolling(40).mean()
S = ((ma40 - ma40.shift(20)) / ma40.shift(20)).values
P = (close/close.shift(10) - 1).values
R = (vol/vol.rolling(5).mean()).values
enough = (close.rolling(60).count().values >= 60)
y_mask = (cal >= 20240101) & (cal <= 20241231)
n = len(cal); FWD, COST = 10, 0.002
W = ['40/40/20','40/20/40','20/50/30','0/50/50','0/100/0']
res = {w: {} for w in W}
for i in np.where(y_mask)[0]:
    if i+1+FWD >= n: continue
    if np.isnan(C[i+1]).all(): continue
    ent_ok = ~np.isnan(C[i+1])
    base = A[i+1]
    fwd = np.where(ent_ok & (base > 0), A[i+1+FWD]/base - 1, np.nan)
    uni = np.nanmedian(fwd)
    sl, p, r_, c_, o_ = S[i], P[i], R[i], C[i], O[i]
    # 三腿原始分（float64，无 kill 预处理；NaN 比较自然=False → 腿分0）
    t_ = np.where(sl > 0.02, 40.0, np.where(sl > 0, 20.0, 0.0))
    ov = np.where(p < -0.08, 40.0, np.where(p < -0.04, 20.0, 0.0))
    vv = np.where((r_ < 0.8) | ((r_ > 1.2) & (c_ > o_)), 20.0, 0.0)
    dead = np.isnan(sl) | (sl < 0) | ~enough[i]
    for w in W:
        wt, wo, wv = [float(x) for x in w.split('/')]
        tot = wt+wo+wv
        s_ = (wt*(t_/40) + wo*(ov/40) + wv*(vv/20)) / tot
        s_[dead] = 0.0
        pool = np.where(s_ >= 0.8)[0]
        if len(pool) < 10: continue
        pf = fwd[pool]; ok = ~np.isnan(pf)
        ps = s_[pool][ok]; pp = p[pool][ok]; pf = pf[ok]
        if len(ps) < 10 or np.isnan(uni): continue
        order = np.lexsort((pp, -ps))[:10]
        res[w][int(cal[i])] = float(pf[order].mean() - uni - COST)
csvd = pd.read_csv(f'{HOME}/.hermes/stockdb/analysis/cmmr_grid_days/2024.csv')
print(f"{'权重':<10} 交集日 最大差pp 日均(独立) 日均(CSV) 独立t")
for w in W:
    mine = pd.Series(res[w]).sort_index()
    cs = csvd[csvd.w == w].copy(); cs['date'] = cs['date'].astype(int)
    cs = cs.set_index('date').ex
    idx = mine.index.intersection(cs.index)
    a = mine.loc[idx].values*100; b = cs.loc[idx].values*100
    def nw_t(v, lag=10):
        v=np.asarray(v); nn=len(v); m=v.mean(); e=v-m
        g=sum(np.cov(e[j:],e[:-j],ddof=1)[0,1]*(1-j/(lag+1)) for j in range(1,lag+1))
        return m/np.sqrt((np.var(v,ddof=1)+2*g)/nn)
    print(f"{w:<10} {len(idx):>4} {np.abs(a-b).max():>8.5f} {a.mean():>+8.4f} {b.mean():>+8.4f} {nw_t(a):>+6.2f}")
