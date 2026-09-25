# -*- coding: utf-8 -*-
"""量化 float32 vs float64 对打分与top10选池的影响（20260918 全市场）"""
import duckdb, sqlite3, os
import numpy as np, pandas as pd
HOME = os.path.expanduser('~')
con = duckdb.connect(f'{HOME}/.hermes/stockdb/tushare.db', read_only=True)
d = '20260918'
df = con.execute(f"""
  SELECT d.ts_code, CAST(d.trade_date AS INT) td, d."open", d.close, d.vol
  FROM daily d WHERE d.trade_date BETWEEN '20260501' AND '{d}'
""").df()
col_order = sorted(df.ts_code.unique())
def piv(c, dt): return df.pivot(index='td', columns='ts_code', values=c).reindex(columns=col_order).astype(dt)
for dtype in ['float32', 'float64']:
    close = piv('close', dtype); opn = piv('open', dtype); vol = piv('vol', dtype)
    C = close.values; O = opn.values
    S = ((close.rolling(40).mean() - close.rolling(20).mean().shift(40)) / close.rolling(20).mean().shift(40)).values
    P = (close/close.shift(10)-1).values
    R = (vol/vol.rolling(5).mean()).values
    enough = close.rolling(60).count().values >= 60
    T = np.where(S > 0.02, 1.0, np.where(S > 0, 0.5, 0.0))
    Ov = np.where(P < -0.08, 1.0, np.where(P < -0.04, 0.5, 0.0))
    V = np.where((R < 0.8) | ((R > 1.2) & (C > O)), 1.0, 0.0)
    kill = (S < 0) | ~enough | np.isnan(C)
    T[kill] = 0; Ov[kill] = 0; V[kill] = 0
    sc_ = (40*T + 40*Ov + 20*V)[-1]
    if dtype == 'float32': sc32 = sc_.copy()
    else: sc64 = sc_.copy()
mism = np.nansum(np.abs(sc32 - sc64) > 1e-9)
print(f'float32 vs float64 打分不一致票数(当日全市场): {mism} / {len(sc64)}')
# 对top10池的影响（≥80 按 分降,p10升 取10）
P64 = P[-1]
def top10(sc_):
    idx = np.where(sc_ >= 80)[0]
    ok = ~np.isnan(P64[idx])
    order = np.lexsort((P64[idx][ok], -sc_[idx][ok]))[:10]
    return set(np.array(col_order)[idx][ok][order])
t32, t64 = top10(sc32), top10(sc64)
print('top10 重合:', len(t32 & t64), '/10')
print('差异:', t32 ^ t64)
