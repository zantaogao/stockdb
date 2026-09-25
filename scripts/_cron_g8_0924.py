#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0924 第七轮：策略账户 R7 浮亏止损距离（现价≤成本×0.94）"""
import sqlite3, duckdb, os, json
BASE = os.path.expanduser('~/.hermes/stockdb')
lc = sqlite3.connect(BASE + '/ledger.db'); lc.row_factory = sqlite3.Row
rows = [dict(r) for r in lc.execute("SELECT * FROM strategy_positions").fetchall()]
tdb = duckdb.connect(BASE + '/tushare.db', read_only=True)
last_td = tdb.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
res = []
for r in rows:
    code = r['code']; ts = code + ('.SH' if code.startswith(('6', '5', '9')) else '.SZ')
    q = tdb.execute("SELECT close FROM daily WHERE ts_code=? AND trade_date=?", (ts, last_td)).fetchone()
    px = q[0] if q else None
    if px and r['avg_cost']:
        gap = (px / (r['avg_cost'] * 0.94) - 1) * 100
        res.append(dict(acc=r['account_id'], code=code, name=r['name'], ac=r['avg_cost'], px=px,
                        gap=round(gap, 2), mv=round(px * r['shares'])))
res.sort(key=lambda x: x['gap'])
print('last_td', last_td, 'n', len(res))
for x in res[:16]:
    print(x)
print('R7 hits:', [x for x in res if x['gap'] <= 0])
print('near(-1%~0):', [x for x in res if -1 < x['gap'] <= 0])
lc.close(); tdb.close()
