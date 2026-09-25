#!/usr/bin/env python3
"""09-10 补充：几个候选权重 vs 基线，按月份拆解逐日IC差（防单月行情撑结论）。"""
import sqlite3, sys
import numpy as np
import pandas as pd
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.db import TUSHARE_DB_PATH, _safe_connect

con = _safe_connect(TUSHARE_DB_PATH, read_only=True)
st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sig_days = [r[0] for r in st.execute(
    "SELECT DISTINCT REPLACE(date,'-','') FROM signal_history "
    "WHERE reg10 IS NOT NULL AND reg20 IS NOT NULL AND reg40 IS NOT NULL "
    "AND fusion_score IS NOT NULL ORDER BY 1").fetchall()]
lo, hi = sig_days[0], sig_days[-1]
px = con.execute(f'''
    SELECT ts_code, trade_date, close FROM daily
    WHERE trade_date BETWEEN '{lo}' AND COALESCE((SELECT MIN(trade_date) FROM daily WHERE trade_date > '{hi}'), '{hi}')
      AND (ts_code LIKE '%.SZ' OR ts_code LIKE '%.SH')
''').df()
con.close()
pxw = px.pivot(index='trade_date', columns='ts_code', values='close').sort_index()
pxw.index = pxw.index.astype(str)
dates = list(pxw.index)
next_ret = pxw.shift(-1) / pxw - 1

def code_to_ts(c):
    c = str(c)
    return c + '.SH' if c.startswith(('600','601','602','603','604','605','688','9')) else c + '.SZ'

days = []
for d in sig_days:
    df = pd.read_sql("SELECT stock_code, reg10, reg20, reg40, fusion_score FROM signal_history WHERE REPLACE(date,'-','')=?",
                     st, params=(d,))
    df['ts'] = df['stock_code'].map(code_to_ts)
    if d not in pxw.index: continue
    nxt = dates.index(d) + 1
    if nxt >= len(dates): continue
    fwd_ser = next_ret.loc[d]
    fwd = pd.DataFrame({'ts': np.asarray(fwd_ser.index, dtype=str), 'fwd': fwd_ser.to_numpy(float)})
    m = df.merge(fwd, left_on='ts', right_on='ts', how='inner')
    m = m.dropna(subset=['fwd','reg10','reg20','reg40','fusion_score'])
    if len(m) < 1000: continue
    R_raw = np.column_stack([m['reg10'].to_numpy(float)*100, m['reg20'].to_numpy(float), m['reg40'].to_numpy(float)])
    R_z = (R_raw - R_raw.mean(0)) / (R_raw.std(0) + 1e-12)
    days.append(dict(date=d, raw=R_raw, z=R_z, fwd=m['fwd'].to_numpy(float), base=m['fusion_score'].to_numpy(float)))
st.close()

cands = [('raw 30/20/50','raw',(0.3,0.2,0.5)), ('raw 30/30/40','raw',(0.3,0.3,0.4)),
         ('raw 50/20/30','raw',(0.5,0.2,0.3)), ('z 20/20/60','z',(0.2,0.2,0.6)),
         ('z 30/10/60','z',(0.3,0.1,0.6)), ('z 40/10/50','z',(0.4,0.1,0.5))]
rows = []
for d in days:
    r = dict(date=d['date'], month=d['date'][:6],
             ic_base=np.corrcoef(d['base'], d['fwd'])[0,1])
    for nm, kind, w in cands:
        r[nm] = np.corrcoef(d[kind] @ np.array(w), d['fwd'])[0,1]
    rows.append(r)
df = pd.DataFrame(rows)
pd.set_option('display.float_format', lambda v: f"{v:.4f}")
print(df.drop(columns=['date']).groupby('month').agg(['count','mean']).to_string())
print("\n逐月差(候选-基线) 与 正天数:")
for nm,_,_ in cands:
    line = [nm.ljust(12)]
    for mo in sorted(df['month'].unique()):
        dif = (df[df.month==mo][nm]-df[df.month==mo]['ic_base']).dropna()
        line.append(f"{mo}: 差{dif.mean():+.4f} 正{int((dif>0).sum())}/{len(dif)}")
    dif_all = df[nm]-df['ic_base']
    line.append(f"全期: 差{dif_all.mean():+.4f} 正{int((dif_all>0).sum())}/{len(dif_all)}")
    print('  '.join(line))
