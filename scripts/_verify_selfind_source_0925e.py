#!/usr/bin/env python3
"""Audit v5: are the 3 obv-diff stocks (600018/000537/000601) suspended/dividend on recent days?
Obv diffs usually trace to 除权除息/停牌 days where tushare resets obv vs self-compute continuing."""
import duckdb, pandas as pd, json

tc = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
ic = duckdb.connect('/Users/zantao/.hermes/stockdb/indicators.db', read_only=True)

codes = ['600018.SH','000537.SZ','000601.SZ']
for c in codes:
    d = tc.execute(
        "SELECT trade_date, vol, close, pct_chg FROM daily WHERE ts_code=? AND trade_date>='20260908' ORDER BY trade_date",
        [c]).df()
    print('=====', c, '最近daily:')
    print(d.to_string(index=False))
    adj = tc.execute(
        "SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? AND trade_date>='20260901' ORDER BY trade_date",
        [c]).df()
    print('adj_factor变化(9月):')
    print(adj.to_string(index=False))
    ob = ic.execute(
        "SELECT trade_date, obv_bfq FROM indicator_bfq WHERE ts_code=? AND trade_date>='20260915' ORDER BY trade_date",
        [c]).df()
    print('自算obv最近:')
    print(ob.to_string(index=False))
