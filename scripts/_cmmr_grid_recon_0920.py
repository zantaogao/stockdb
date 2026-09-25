# -*- coding: utf-8 -*-
"""对账：_cmmr_grid_year_0920 的阶梯打分 vs 生产 signal_history.cmmr_score 逐票比对
覆盖 signal_history 全部有分日期（20260724~20260918, 31天）"""
import duckdb, sqlite3, os
import numpy as np, pandas as pd
HOME = os.path.expanduser('~')
con = duckdb.connect(f'{HOME}/.hermes/stockdb/tushare.db', read_only=True)
sc = sqlite3.connect(f'file:{HOME}/.hermes/stockdb/signals.db?mode=ro', uri=True)

sig = sc.execute("SELECT REPLACE(date,'-','') d, stock_code, cmmr_score FROM signal_history WHERE cmmr_score>0").fetchall()
dates = sorted({r[0] for r in sig})
lo = (pd.Timestamp(dates[0]) - pd.Timedelta(days=120)).strftime('%Y%m%d')
hi = dates[-1]
df = con.execute(f"""
  SELECT d.ts_code, CAST(d.trade_date AS INT) td, d."open", d.close, d.vol
  FROM daily d WHERE d.trade_date BETWEEN '{lo}' AND '{hi}'
""").df()
col_order = sorted(df.ts_code.unique())
def piv(c): return df.pivot(index='td', columns='ts_code', values=c).reindex(columns=col_order).astype('float32')
close = piv('close'); opn = piv('open'); vol = piv('vol')
cal = np.array(close.index); ci = {d: i for i, d in enumerate(cal)}
idx = pd.Index(col_order)
C = close.values; O = opn.values
ma40_ = close.rolling(40).mean()
S = ((ma40_ - ma40_.shift(20)) / ma40_.shift(20)).values
P = (close/close.shift(10)-1).values
R = (vol/vol.rolling(5).mean()).values
enough = close.rolling(60).count().values >= 60
T = np.where(S > 0.02, 1.0, np.where(S > 0, 0.5, 0.0))
Ov = np.where(P < -0.08, 1.0, np.where(P < -0.04, 0.5, 0.0))
V = np.where((R < 0.8) | ((R > 1.2) & (C > O)), 1.0, 0.0)
kill = (S < 0) | ~enough | np.isnan(C)
T[kill] = 0; Ov[kill] = 0; V[kill] = 0
score = (40*T + 40*Ov + 20*V)  # 现行权重原分制

match = tot = 0
diffs = []
for dstr, code, cs in sig:
    if '.' in code:
        ts = code
    else:
        ts = code + ('.SH' if code[:1] in ('6','9') else ('.BJ' if code[:1] in ('4','8') else '.SZ'))
    t = int(dstr)
    if t not in ci or ts not in idx: 
        diffs.append((dstr, code, 'no_row', cs, None)); continue
    j = idx.get_loc(ts)
    mine = float(score[ci[t], j])
    tot += 1
    if abs(mine - float(cs)) < 1e-6: match += 1
    else: diffs.append((dstr, code, 'val', float(cs), mine))
print(f'逐票对账: {match}/{tot} 一致 = {100*match/max(tot,1):.2f}%')
from collections import Counter
bad = Counter((a if a != 'val' else 'val') for a, *_ in diffs)
print('差异类型:', dict(bad))
for r in diffs[:15]: print(r)
