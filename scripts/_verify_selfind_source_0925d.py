#!/usr/bin/env python3
"""Audit v4: identify the 3 obv-diff stocks on 20260924 (extra.obv_bfq vs indicator_bfq.obv_bfq)."""
import duckdb, pandas as pd, json

tc = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
ic = duckdb.connect('/Users/zantao/.hermes/stockdb/indicators.db', read_only=True)

sf = tc.execute("SELECT ts_code, extra FROM stk_factor WHERE trade_date='20260924'").df()
ind = ic.execute("SELECT ts_code, obv_bfq FROM indicator_bfq WHERE trade_date='20260924'").df()

a = sf.set_index('ts_code')['extra'].apply(lambda s: json.loads(s).get('obv_bfq') if isinstance(s, str) else None)
a = pd.to_numeric(a, errors='coerce')
b = pd.to_numeric(ind.set_index('ts_code')['obv_bfq'], errors='coerce')
m = pd.concat([a, b], axis=1, keys=['sf', 'ind']).dropna()
diff = (m['sf'] - m['ind']).abs()
tol = 0.005 * (1 + m['sf'].abs())
bad = m[diff > tol]
print(bad)

codes = list(bad.index)
# do these 3 appear in either Top10?
top = ['688121.SH','300430.SZ','301030.SZ','603359.SH','603585.SH','300492.SZ','001225.SZ','688117.SH','688377.SH','300147.SZ']
print('是否有人在Top10:', [c for c in codes if c in top])
# what does obv feed? check scoring feature list
import subprocess
r = subprocess.run(['grep','-rn','obv','/Users/zantao/.hermes/stockdb/core/features.py'], capture_output=True, text=True)
print(r.stdout[:1500])
