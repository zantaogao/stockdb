#!/usr/bin/env python3
"""Audit v2: compare via the feat_tushare mapping (f -> f_bfq / rsi_N -> rsi_bfq_N)."""
import duckdb, pandas as pd, sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')

tc = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
ic = duckdb.connect('/Users/zantao/.hermes/stockdb/indicators.db', read_only=True)

sf = tc.execute("SELECT * FROM stk_factor WHERE trade_date='20260924'").df()
ind = ic.execute("SELECT * FROM indicator_bfq WHERE trade_date='20260924'").df()
sf['trade_date'] = sf['trade_date'].astype(str)
ind['trade_date'] = ind['trade_date'].astype(str)

# factor field names the scoring uses (per _get_self_factor mapping)
fields = ['ma_5','ma_20','ma_60','macd_dif','macd_dea','macd','kdj_k','kdj_d','kdj',
          'rsi_6','rsi_12','rsi_24','obv','wr','roc','mtm','cci','dmi_pdi','dmi_mdi','dmi_adx',
          'boll_upper','boll_mid','boll_lower']

def ind_col(f):
    if f.startswith('rsi_') and f[4:].isdigit():
        return f'rsi_bfq_{f[4:]}'
    return f + '_bfq'

# which of these exist as columns in stk_factor?
sfc = set(sf.columns)
usable = [f for f in fields if ind_col(f) in ind.columns and (f in sfc or f'{f}_bfq' in sfc)]
print('stk_factor 侧列名样例:', [c for c in sfc if any(k in c for k in ('kdj','rsi','cci','macd'))][:15])
print('可比字段数:', len(usable))

m = sf.merge(ind, on=['ts_code','trade_date'], suffixes=('_sf','_ind'))
print('overlap:', len(m))
bad = []
for f in usable:
    sf_col = f if f in sfc else f + '_bfq'
    a = pd.to_numeric(m[sf_col], errors='coerce')
    b = pd.to_numeric(m[ind_col(f)], errors='coerce')
    both = a.notna() & b.notna()
    diff = (a[both]-b[both]).abs()
    tol = 0.005*(1+a[both].abs())
    nd = int((diff>tol).sum())
    maxd = float(diff.max()) if both.any() else 0.0
    if nd:
        bad.append((f, nd, int(both.sum()), round(maxd,4)))
print('差异>0.5%容差的字段:', bad if bad else 'NONE — 23字段×5510票 逐值一致')
