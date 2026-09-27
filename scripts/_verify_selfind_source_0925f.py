#!/usr/bin/env python3
"""Audit v6: for 600018/000537/000601 — compare obv deltas: tushare extra obv_bfq day-over-day
vs daily vol*pct_chg sign. Whichever matches the K-line volume is correct; the other side has
a stale/offset row. Covers 20260908..20260924."""
import duckdb, pandas as pd, json

tc = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
ic = duckdb.connect('/Users/zantao/.hermes/stockdb/indicators.db', read_only=True)

for code in ['600018.SH', '000537.SZ', '000601.SZ']:
    sf = tc.execute(
        "SELECT trade_date, extra FROM stk_factor WHERE ts_code=? AND trade_date>='20260901' ORDER BY trade_date",
        [code]).df()
    sf['obv_tushare'] = sf['extra'].apply(lambda s: json.loads(s).get('obv_bfq'))
    ind = ic.execute(
        "SELECT trade_date, obv_bfq FROM indicator_bfq WHERE ts_code=? AND trade_date>='20260901' ORDER BY trade_date",
        [code]).df().rename(columns={'obv_bfq': 'obv_self'})
    d = tc.execute(
        "SELECT trade_date, vol, pct_chg FROM daily WHERE ts_code=? AND trade_date>='20260901' ORDER BY trade_date",
        [code]).df()
    m = d.merge(sf[['trade_date', 'obv_tushare']], on='trade_date', how='left') \
         .merge(ind, on='trade_date', how='left')
    m['vol_signed_wan'] = m['vol'] * (m['pct_chg'] > 0) - m['vol'] * (m['pct_chg'] < 0)  # 手->万手需/10000
    m['delta_tushare'] = m['obv_tushare'].diff()
    m['delta_self'] = m['obv_self'].diff()
    # vol unit: 手; obv unit 万手 presumably
    m['vol_signed'] = m['vol_signed_wan'] / 10000.0
    print('=====', code)
    print(m[['trade_date', 'pct_chg', 'vol_signed', 'delta_tushare', 'delta_self']].round(3).to_string(index=False))
