#!/usr/bin/env python3
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
print("hi =", repr(hi), type(hi))
px = con.execute(f'''
    SELECT ts_code, trade_date, close FROM daily
    WHERE trade_date BETWEEN '{lo}' AND (SELECT MIN(trade_date) FROM daily WHERE trade_date > '{hi}')
      AND (ts_code LIKE '%.SZ' OR ts_code LIKE '%.SH')
''').df()
print("px rows:", len(px), px['trade_date'].unique()[:3])
pxw = px.pivot(index='trade_date', columns='ts_code', values='close').sort_index()
pxw.index = pxw.index.astype(str)
print("index:", pxw.index[:3], pxw.index.dtype)
d = sig_days[5]
print("d =", repr(d), type(d), "in index:", d in pxw.index)
con.close(); st.close()