#!/usr/bin/env python3
"""09-06 中枢版 x CMMR 配合实验 v2（清洗版，逐日IC + 汇总NW-t + Top10）。"""
import sqlite3, sys
import numpy as np, pandas as pd
from scipy.stats import spearmanr
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.db import TUSHARE_DB_PATH, _safe_connect

def code_to_ts(c):
    c = str(c)
    return c + '.SH' if c.startswith(('600','601','602','603','604','605','688','9')) else c + '.SZ'

def nw_t(x, lag=5):
    x = np.asarray(x, float); n = len(x)
    if n < 8: return np.nan
    e = x - x.mean(); s = (e @ e) / n
    for l in range(1, lag + 1):
        s += 2 * (1 - l/(lag+1)) * (e[l:] @ e[:-l]) / n
    return x.mean() / np.sqrt(s/n) if s > 0 else np.nan

def top10_ret(score, ret):
    idx = np.argsort(score)[::-1][:10]
    return ret[idx].mean()

con = _safe_connect(TUSHARE_DB_PATH, read_only=True)
alldates = [r[0] for r in con.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date>='20260801' AND (ts_code LIKE '%.SZ' OR ts_code LIKE '%.SH') ORDER BY 1").fetchall()]
st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
days = [r[0] for r in st.execute("""
  SELECT DISTINCT REPLACE(c.date,'-','') FROM fusion_center_signals c
  JOIN signal_history s ON REPLACE(s.date,'-','')=REPLACE(c.date,'-','') AND s.stock_code=c.stock_code
  WHERE c.stock_code!='__market_state__' AND c.score IS NOT NULL AND s.cmmr_score IS NOT NULL ORDER BY 1""").fetchall()]
st.close()

res = []
for d in days:
    i = alldates.index(d) if d in alldates else -1
    if i < 0 or i+1 >= len(alldates): continue
    nd = alldates[i+1]
    st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
    df = pd.read_sql("""
      SELECT c.stock_code, c.score AS center, s.cmmr_score, s.fusion_score
      FROM fusion_center_signals c
      JOIN signal_history s ON REPLACE(s.date,'-','')=REPLACE(c.date,'-','') AND s.stock_code=c.stock_code
      WHERE c.stock_code!='__market_state__' AND REPLACE(c.date,'-','')=?
        AND c.score IS NOT NULL AND s.cmmr_score IS NOT NULL""", st, params=(d,))
    st.close()
    if len(df) < 1000: continue
    df['ts'] = df['stock_code'].map(code_to_ts)
    con2 = _safe_connect(TUSHARE_DB_PATH, read_only=True)
    px = con2.execute(f"SELECT ts_code, trade_date, close FROM daily WHERE trade_date IN ('{d}','{nd}') AND ts_code IN (SELECT UNNEST(?))", (df['ts'].tolist(),)).df()
    con2.close()
    p = px.pivot(index='ts_code', columns='trade_date', values='close')
    if nd not in p.columns: 
        print('未成熟', d); continue
    df = df.merge(p.rename(columns={d:'c0', nd:'c1'})[['c0','c1']], left_on='ts', right_index=True)
    df['ret'] = df['c1']/df['c0'] - 1
    df = df.dropna(subset=['ret','center','cmmr_score'])
    if len(df) < 1000: continue
    pc = df['center'].rank(pct=True).to_numpy(); pm = df['cmmr_score'].rank(pct=True).to_numpy()
    ret = df['ret'].to_numpy()
    row = dict(date=d, n=len(df),
               ic_center=spearmanr(pc, ret).statistic,
               ic_cmmr=spearmanr(pm, ret).statistic,
               xcorr=spearmanr(pc, pm).statistic)
    fs = df['fusion_score'].to_numpy(float)
    ok = np.isfinite(fs)
    if ok.sum() == len(df):
        row['ic_fusion'] = spearmanr(pd.Series(fs).rank(pct=True), ret).statistic
    for w in (0.3, 0.5, 0.7):
        b = w*pc + (1-w)*pm
        row[f'ic_mix{int(w*10)}'] = spearmanr(b, ret).statistic
        row[f'top10_mix{int(w*10)}'] = top10_ret(b, ret)
    ct = pc >= np.quantile(pc, 0.8)   # 中枢Top20%
    mt = pm >= np.quantile(pm, 0.8)   # CMMR Top20%
    if ct.sum() >= 200:
        row['ic_g_c2m'] = spearmanr(pm[ct], ret[ct]).statistic      # 中枢门内用CMMR排
        row['top10_g_c2m'] = top10_ret(pm[ct], ret[ct])
        row['top10_c'] = top10_ret(pc[ct], ret[ct])                 # 中枢门内用中枢排
    if mt.sum() >= 200:
        row['ic_g_m2c'] = spearmanr(pc[mt], ret[mt]).statistic
        row['top10_g_m2c'] = top10_ret(pc[mt], ret[mt])
        row['top10_m'] = top10_ret(pm[mt], ret[mt])
    both = ct & mt
    if both.sum() >= 50:
        row['n_both'] = int(both.sum())
        row['top10_both'] = top10_ret(pc[both]+pm[both], ret[both])
    row['top10_center'] = top10_ret(pc, ret)
    row['top10_cmmr'] = top10_ret(pm, ret)
    if ok.sum() == len(df):
        row['top10_fusion'] = top10_ret(fs, ret)
    res.append(row)

df = pd.DataFrame(res)
cols = ['date','n','ic_center','ic_cmmr','xcorr','ic_fusion','ic_mix3','ic_mix5','ic_mix7','ic_g_c2m','ic_g_m2c']
print(df[cols].to_string(index=False, float_format=lambda v: f"{v:.4f}"))
n = len(df)
print(f"\n===== 汇总 n={n} 成熟日 =====")
ref = df['ic_mix5']
for c in [x for x in df.columns if x.startswith('ic_')]:
    s = df[c].dropna()
    line = f"{c:10s}: 均值IC={s.mean():+.4f} IR={s.mean()/(s.std()+1e-12):.3f} 胜率={(s>0).mean():.0%}"
    if c != 'ic_mix5':
        dif = (s - ref).dropna()
        line += f"  差(vs mix5)={dif.mean():+.4f} NW-t={nw_t(dif):.2f}"
    print(line)
print(f"\n两信号冗余(截面Spearman): 均值={df['xcorr'].mean():+.3f} 范围[{df['xcorr'].min():+.3f},{df['xcorr'].max():+.3f}]")
t10 = [x for x in df.columns if x.startswith('top10_')]
print("\nTop10 等权次日收益均值:")
for c in t10:
    print(f"  {c}: {df[c].mean():+.4f}")
df.to_csv('/Users/zantao/.hermes/stockdb/reports/center_cmmr_0906.csv', index=False)
print("\n明细已存 reports/center_cmmr_0906.csv")