#!/usr/bin/env python3
"""Audit v3: correct default-side path = stk_factor.extra JSON (_bfq keys)."""
import duckdb, pandas as pd, json

tc = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
ic = duckdb.connect('/Users/zantao/.hermes/stockdb/indicators.db', read_only=True)

sf = tc.execute("SELECT ts_code, extra FROM stk_factor WHERE trade_date='20260924'").df()
ind = ic.execute("SELECT * FROM indicator_bfq WHERE trade_date='20260924'").df()

fields = ['ma_5','ma_20','ma_60','macd_dif','macd_dea','macd','kdj_k','kdj_d','kdj',
          'rsi_6','rsi_12','rsi_24','obv','wr','roc','mtm','cci','dmi_pdi','dmi_mdi','dmi_adx',
          'boll_upper','boll_mid','boll_lower']

def ind_col(f):
    if f.startswith('rsi_') and f[4:].isdigit():
        return f'rsi_bfq_{f[4:]}'
    return f + '_bfq'

# parse extra JSON into bfq-keyed columns
extras = sf.set_index('ts_code')['extra'].apply(lambda s: json.loads(s) if isinstance(s, str) else {})
keys_needed = {ind_col(f) for f in fields}
present = sorted(keys_needed & set().union(*[set(e.keys()) for e in extras.head(50)]))
print('extra 里可用的 _bfq 键数:', len(present))

rows = []
for f in fields:
    col = ind_col(f)
    if col not in present:
        continue
    a = extras.reindex(sf.ts_code).apply(lambda e: e.get(col))
    a = pd.to_numeric(pd.Series(list(a), index=sf.ts_code), errors='coerce')
    b = pd.to_numeric(ind.set_index('ts_code')[col], errors='coerce')
    m = pd.concat([a, b], axis=1, keys=['sf','ind']).dropna()
    if not len(m):
        continue
    diff = (m['sf'] - m['ind']).abs()
    tol = 0.005 * (1 + m['sf'].abs())
    nd = int((diff > tol).sum())
    if nd:
        rows.append((f, nd, len(m), round(float(diff.max()), 4)))

print('差异>0.5%容差字段:', rows if rows else 'NONE — extra(_bfq) vs indicator_bfq 逐值一致')

# spot check 3 stocks on kdj_k/rsi_12
sample = list(sf.ts_code[:3])
for f in ['kdj_k','rsi_12','cci']:
    col = ind_col(f)
    for c in sample:
        print(c, f, 'stk_factor.extra=', extras[c].get(col), 'indicator_bfq=', ind.set_index('ts_code')[col].get(c))
