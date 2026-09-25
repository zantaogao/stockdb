#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0924 第九轮：布林位置 + 指数支撑位"""
import duckdb, os, json
tdb = duckdb.connect(os.path.expanduser('~/.hermes/stockdb/tushare.db'), read_only=True)
codes = ['603585','001225','300492','688117','688377','301590','300970','603811','300854','603090',
 '000017','000019','000428','000430','000505','000523','000524','000533','000553','000554',
 '600262','301156','300614','605077','002535','002809','002661',
 '603823','600499','300413','000668','603999','002961','003040',
 '000952','600048','002133','300564','688500','603079','600875','300136','002881',
 '300055','300533','603737','600785','301232','600791','300228','300898']
res = {}
for c in codes:
    ts = c + ('.SH' if c.startswith(('6', '5', '9')) else '.SZ')
    d = tdb.execute("SELECT trade_date, close FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 21", (ts,)).fetchall()
    if len(d) < 21: continue
    closes = [x[1] for x in d][::-1]
    last = closes[-1]
    ma20 = sum(closes[-20:]) / 20
    var = sum((x - ma20) ** 2 for x in closes[-20:]) / 20
    sd = var ** 0.5
    up, lo = ma20 + 2 * sd, ma20 - 2 * sd
    pos = (last - lo) / (up - lo) * 100
    hi20 = max(closes[-20:])
    res[c] = dict(boll=round(pos, 1), ma20dev=round((last / ma20 - 1) * 100, 1),
                  hi20=round((last / hi20 - 1) * 100, 1), upd=round(up, 2), lod=round(lo, 2), last=last)
out = {'boll': res}
# 指数
for ts, nm in [('000852.SH', '中证1000'), ('000001.SH', '上证')]:
    d = tdb.execute("SELECT trade_date, close, low, high FROM index_daily_raw WHERE ts_code=? ORDER BY trade_date DESC LIMIT 25", (ts,)).fetchall()
    closes = [x[1] for x in d][::-1]
    ma10 = sum(closes[-10:]) / 10; ma20 = sum(closes[-20:]) / 20
    out[nm] = dict(last=closes[-1], ma10=round(ma10, 1), ma20=round(ma20, 1),
                   hi20=round(max(closes[-20:]), 1), lo20=round(min(closes[-20:]), 1),
                   hi5=round(max(closes[-5:]), 1), lo5=round(min(closes[-5:]), 1),
                   gap_ref=[(x[0], x[1]) for x in d[:8]])
tdb.close()
print(json.dumps(out, ensure_ascii=False, default=str, indent=1))
