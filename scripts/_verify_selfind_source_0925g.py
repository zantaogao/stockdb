#!/usr/bin/env python3
"""Audit v7: locate the historical date where tushare extra obv_bfq jumps vs self-computed
obv_bfq for 600018/000537/000601 — expect a single reset day (tushare re-seeds obv),
constant offset on all other days. If so: level diff is a known tushare re-anchor artifact,
deltas identical -> ranking impact ~0 (obv likely rank-transformed)."""
import duckdb, pandas as pd, json

tc = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
ic = duckdb.connect('/Users/zantao/.hermes/stockdb/indicators.db', read_only=True)

for code in ['600018.SH', '000537.SZ', '000601.SZ']:
    sf = tc.execute(
        "SELECT trade_date, extra FROM stk_factor WHERE ts_code=? ORDER BY trade_date", [code]).df()
    sf['obv_t'] = sf['extra'].apply(lambda s: json.loads(s).get('obv_bfq') if isinstance(s, str) else None)
    ind = ic.execute(
        "SELECT trade_date, obv_bfq AS obv_s FROM indicator_bfq WHERE ts_code=? ORDER BY trade_date", [code]).df()
    m = sf[['trade_date', 'obv_t']].merge(ind, on='trade_date', how='inner')
    m['offset'] = pd.to_numeric(m['obv_t']) - pd.to_numeric(m['obv_s'])
    # find day where offset changes materially
    m['offset_change'] = m['offset'].diff()
    jumps = m[m['offset_change'].abs() > 1.0]
    print('=====', code, '共同日期数:', len(m), '| offset首个值:', round(float(m['offset'].iloc[0]), 2) if len(m) else None)
    print('offset跳变日:', jumps[['trade_date', 'offset', 'offset_change']].round(2).to_string(index=False) if len(jumps) else '无（两轨obv平行，恒定偏移）')
