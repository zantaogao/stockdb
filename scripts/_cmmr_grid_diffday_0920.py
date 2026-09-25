# -*- coding: utf-8 -*-
"""定位 xcheck 独立链 vs 逐年链 2024 逐日分歧：印 |差| 最大的10天，含两边池子大小"""
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
  WHERE d.trade_date BETWEEN '20240101' AND '20241231'
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
n = len(cal); FWD, COST = 10, 0.002
W = '40/40/20'; wt, wo, wv = 40., 40., 20.; tot = 100.
mine, pool_mine = {}, {}
for i in range(n):
    if np.isnan(C[i+1]).all() if i+1 < n else True: continue
    if i+1+FWD >= n: continue
    ent_ok = ~np.isnan(C[i+1])
    fwd = np.where(ent_ok & (A[i+1] > 0), A[i+1+FWD]/A[i+1] - 1, np.nan)
    uni = np.nanmedian(fwd)
    sl, p, r_, c_, o_ = S[i], P[i], R[i], C[i], O[i]
    t_ = np.where(sl > 0.02, 1.0, np.where(sl > 0, 0.5, 0.0))
    ov = np.where(p < -0.08, 1.0, np.where(p < -0.04, 0.5, 0.0))
    vv = np.where((r_ < 0.8) | ((r_ > 1.2) & (c_ > o_)), 1.0, 0.0)
    dead = np.isnan(sl) | (sl < 0) | ~enough[i]
    s_ = (wt*t_ + wo*ov + wv*vv)/tot
    s_[dead] = 0.0
    pool = np.where(s_ >= 0.8)[0]
    pool_mine[int(cal[i])] = len(pool)
    if len(pool) < 10: continue
    pf = fwd[pool]; ok = ~np.isnan(pf)
    ps = s_[pool][ok]; pp = p[pool][ok]; pf = pf[ok]
    if len(ps) < 10 or np.isnan(uni): continue
    order = np.lexsort((pp, -ps))[:10]
    mine[int(cal[i])] = float((pf[order].mean() - uni - COST)*100)
cs = pd.read_csv(f'{HOME}/.hermes/stockdb/analysis/cmmr_grid_days/2024.csv')
cs = cs[cs.w == W].copy(); cs['date'] = cs['date'].astype(int)
cs['ex_pp'] = cs.ex*100
m = pd.Series(mine).rename('mine'); pm = pd.Series(pool_mine).rename('pool_mine')
j = cs.set_index('date')[['pool_n','ex_pp']].join(m).join(pm).dropna(subset=['mine'])
j['diff'] = j.mine - j.ex_pp
print(j.reindex(j['diff'].abs().sort_values(ascending=False).index).head(10).round(2).to_string())
print('交集日', len(j), '符号相反天数', int((np.sign(j.mine) != np.sign(j.ex_pp)).sum()))
