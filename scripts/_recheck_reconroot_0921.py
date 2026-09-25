# -*- coding: utf-8 -*-
"""recon根因：signal_history里 prod存的 ma40_slope 是复权还是不复权口径 + cmmr_score差异票重算"""
import duckdb, sqlite3, os
import numpy as np, pandas as pd
HOME = os.path.expanduser('~')
sc = sqlite3.connect(f'file:{HOME}/.hermes/stockdb/signals.db?mode=ro', uri=True)
print('date样本:', sc.execute("SELECT DISTINCT date FROM signal_history ORDER BY date DESC LIMIT 3").fetchall())
D = sc.execute("SELECT MAX(date) FROM signal_history").fetchone()[0]
prod = sc.execute("SELECT stock_code, cmmr_score, ma40_slope FROM signal_history WHERE date=?", (D,)).fetchall()
sc.close()
def bare(c): return str(c).split('.')[0]
pscore = {bare(c): (v, s) for c, v, s in prod}
print('prod行数', len(pscore), 'date', D)
d8 = str(D).replace('-', '')[:8]
con = duckdb.connect(f'{HOME}/.hermes/stockdb/tushare.db', read_only=True)
lo = str(int(d8[:4]) - 1) + d8[4:]
df = con.execute(f"""
  SELECT d.ts_code, CAST(d.trade_date AS INT) td, d.close, d.vol, a.adj_factor
  FROM daily d LEFT JOIN adj_factor a USING (ts_code, trade_date)
  WHERE d.trade_date BETWEEN '{lo}' AND '{d8}'
""").df()
con.close()
col_order = sorted(df.ts_code.unique())
def piv(c): return df.pivot(index='td', columns='ts_code', values=c).reindex(columns=col_order)
close = piv('close'); adjf = piv('adj_factor').ffill().fillna(1.0)
Aadj = (close * adjf).ffill()
i = list(close.index).index(int(d8))
def sl_p10(mat):
    m40 = mat.rolling(40).mean(); m40l = m40.shift(20)
    return ((m40 - m40l) / m40l).iloc[i], (mat / mat.shift(10) - 1).iloc[i]
Sa, Pa = sl_p10(Aadj); Sr, Pr = sl_p10(close)
idx = pd.Index(col_order)
rows = []
for code, (pv, ps) in pscore.items():
    cand = [f'{code}.{s}' for s in ('SH', 'SZ', 'BJ') if f'{code}.{s}' in idx]
    if not cand: continue
    ts = cand[0]
    sl, p, slr = Sa[ts], Pa[ts], Sr[ts]
    if pd.isna(sl) or sl < 0: mine = 0.0
    else:
        t = 40 if sl > 0.02 else (20 if sl > 0 else 0)
        ov = 40 if p < -0.08 else (20 if p < -0.04 else 0)
        mine = float(t + ov)
    if abs(mine - pv) > 0.5:
        rows.append((code, pv, mine, ps, None if pd.isna(sl) else float(sl),
                     None if pd.isna(slr) else float(slr),
                     None if pd.isna(p) else float(p), None if pd.isna(Pr[ts]) else float(Pr[ts])))
print('差异票(略vol腿):', len(rows), '/', len(pscore))
print(f"{'代码':<8}{'prod':>5}{'mine':>5}{'prod_sl':>9}{'adj_sl':>9}{'raw_sl':>9}{'adj_p10%':>9}{'raw_p10%':>9}")
for r in sorted(rows, key=lambda x: -abs(x[1]-x[2]))[:12]:
    f = lambda v: '   nan' if v is None else f'{v:7.4f}'
    pc = lambda v: ' nan' if v is None else f'{v*100:6.2f}'
    print(f"{r[0]:<8}{r[1]:>5.0f}{r[2]:>5.0f}{f(r[3])}{f(r[4])}{f(r[5])}{pc(r[6]):>9}{pc(r[7]):>9}")
ma = sum(1 for r in rows if r[3] is not None and r[4] is not None and abs(r[3]-r[4]) < 1e-5)
mr = sum(1 for r in rows if r[3] is not None and r[5] is not None and abs(r[3]-r[5]) < 1e-5)
print(f'prod_slope≈复权: {ma}  ≈不复权raw: {mr}  / {len(rows)}')
