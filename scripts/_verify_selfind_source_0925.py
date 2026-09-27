#!/usr/bin/env python3
"""One-off audit: are indicator_bfq rows for 20260924 actually self-computed,
or a verbatim copy of stk_factor? Compare common columns across all codes."""
import duckdb, pandas as pd

tc = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
ic = duckdb.connect('/Users/zantao/.hermes/stockdb/indicators.db', read_only=True)

sf_cols = [d[0] for d in tc.execute("DESCRIBE SELECT * FROM stk_factor LIMIT 1").fetchall()]
ind_cols = [d[0] for d in ic.execute("DESCRIBE SELECT * FROM indicator_bfq LIMIT 1").fetchall()]
common = [c for c in sf_cols if c in ind_cols and c not in ('ts_code', 'trade_date', 'name')]
print('common factor cols:', len(common), common)

sf = tc.execute("SELECT * FROM stk_factor WHERE trade_date='20260924'").df()
ind = ic.execute("SELECT * FROM indicator_bfq WHERE trade_date='20260924'").df()
sf['trade_date'] = sf['trade_date'].astype(str)
ind['trade_date'] = ind['trade_date'].astype(str)
m = sf.merge(ind, on=['ts_code', 'trade_date'], suffixes=('_sf', '_ind'))
print('overlap rows:', len(m), '| sf rows:', len(sf), '| ind rows:', len(ind))

bad = []
for col in common:
    a = pd.to_numeric(m[col + '_sf'], errors='coerce')
    b = pd.to_numeric(m[col + '_ind'], errors='coerce')
    both = a.notna() & b.notna()
    diff = (a[both] - b[both]).abs()
    tol = 0.005 * (1 + a[both].abs())
    nd = int((diff > tol).sum())
    if nd:
        bad.append((col, nd, int(both.sum())))
print('cols with >0.5% diffs:', bad if bad else 'NONE - 两端口径逐列一致')

only_sf = set(sf.ts_code) - set(ind.ts_code)
only_ind = set(ind.ts_code) - set(sf.ts_code)
print('stk_factor有而自算无:', len(only_sf), '| 自算有而stk_factor无:', len(only_ind))

# historical: when did indicator_bfq last get new trade_dates vs stk_factor?
print('ind 最近5个日期:', sorted(ind_dates := [r[0] for r in ic.execute("SELECT DISTINCT trade_date FROM indicator_bfq WHERE trade_date>='20260901' ORDER BY trade_date DESC LIMIT 15").fetchall()]))
print('sf  最近5个日期:', [r[0] for r in tc.execute("SELECT DISTINCT trade_date FROM stk_factor WHERE trade_date>='20260901' ORDER BY trade_date DESC LIMIT 15").fetchall()])
