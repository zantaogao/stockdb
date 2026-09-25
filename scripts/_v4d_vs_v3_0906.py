#!/usr/bin/env python3
"""v4d vs v3 差异度（内存版，一次读三表，绕开 replace() join 不走索引的慢查询）"""
import sqlite3, numpy as np, pandas as pd
from scipy import stats as sps
st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
d4 = pd.read_sql_query("select date, code, score from shadow_v4d_scores", st)
db = pd.read_sql_query("select date, code, score from shadow_v4big_scores", st)
sig = pd.read_sql_query("select replace(date,'-','') date, stock_code code, reg10 from signal_history", st)
sig = sig.drop_duplicates(subset=['code','date'])
m = d4.merge(db, on=['date','code'], suffixes=('','_big')).merge(sig, on=['date','code'])
print(f"覆盖日数 {m['date'].nunique()}，总行数 {len(m)}")
for d, g in m.groupby('date'):
    if len(g) < 100: continue
    g = g.dropna(subset=['score','score_big','reg10'])
    r_v3 = sps.spearmanr(g.score, g.reg10)[0]
    r_vb = sps.spearmanr(g.score, g.score_big)[0]
    k = 50
    t4 = set(g.nlargest(k,'score').index); t3 = set(g.nlargest(k,'reg10').index); tb = set(g.nlargest(k,'score_big').index)
    x = g['reg10'].to_numpy(); y = g['score'].to_numpy()
    resid = y - np.polyval(np.polyfit(x, y, 1), x)
    rr = sps.spearmanr(resid, g['score_big'].to_numpy())[0]
    print(f"{d} n={len(g)} rho(v4d,v3)={r_v3:.3f} top50重合(v3) {len(t4&t3)}/{k} | rho(v4d,v4big)={r_vb:.3f} top50重合(v4big) {len(t4&tb)}/{k} | v4d对v3残差~v4big {rr:.3f}")