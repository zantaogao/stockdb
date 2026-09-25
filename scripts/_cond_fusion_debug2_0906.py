#!/usr/bin/env python3
"""逐环节诊断为何 days 为空。"""
import sqlite3, sys
import numpy as np, pandas as pd
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.db import TUSHARE_DB_PATH, _safe_connect

con = _safe_connect(TUSHARE_DB_PATH, read_only=True)
st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sig_days = [r[0] for r in st.execute(
    "SELECT DISTINCT REPLACE(date,'-','') FROM signal_history "
    "WHERE reg10 IS NOT NULL AND reg20 IS NOT NULL AND reg40 IS NOT NULL "
    "AND fusion_score IS NOT NULL ORDER BY 1").fetchall()]
lo, hi = sig_days[0], sig_days[-1]
px = con.execute(f"SELECT ts_code, trade_date, close FROM daily WHERE trade_date BETWEEN '{lo}' AND '{hi}' AND (ts_code LIKE '%.SZ' OR ts_code LIKE '%.SH')").df()
print("px:", px.shape, px['trade_date'].dtype)
pxw = px.pivot(index='trade_date', columns='ts_code', values='close').sort_index()
pxw.index = pxw.index.astype(str)
print("pxw index样例:", list(pxw.index[:3]), type(pxw.index[0]))
next_ret = pxw.shift(-1)/pxw - 1
dates = list(pxw.index)

d = sig_days[1] if len(sig_days)>1 else sig_days[0]
print("试算日:", d, "in pxw:", d in pxw.index)
df = pd.read_sql("SELECT stock_code, reg10, reg20, reg40, fusion_score FROM signal_history WHERE date=?", st, params=(d,))
print("信号行:", len(df), "非空:", df[['reg10','reg20','reg40','fusion_score']].notna().sum().to_dict())
def code_to_ts(c):
    c=str(c); return c+'.SH' if c.startswith(('600','601','602','603','604','605','688','9')) else c+'.SZ'
df['ts'] = df['stock_code'].map(code_to_ts)
print("ts样例:", df['ts'].head(3).tolist())
fwd = next_ret.loc[d].rename('fwd')
print("fwd非空:", fwd.notna().sum())
m = df.merge(fwd.reset_index(), left_on='ts', right_index=True, how='inner')
print("merge后:", len(m), m.dropna(subset=['fwd','reg10','reg20','reg40','fusion_score']).shape)
con.close(); st.close()