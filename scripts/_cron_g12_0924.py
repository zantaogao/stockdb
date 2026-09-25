#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import duckdb, os
tdb = duckdb.connect(os.path.expanduser('~/.hermes/stockdb/tushare.db'), read_only=True)
for c, nm in [('300658', '延江股份'), ('301575', '艾芬达'), ('301093', '华兰股份'), ('600076', '康欣新材')]:
    ts = c + ('.SH' if c.startswith(('6', '5', '9')) else '.SZ')
    d = [x[1] for x in tdb.execute("SELECT trade_date, close FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 21", (ts,)).fetchall()][::-1]
    last = d[-1]; ma20 = sum(d[-20:])/20
    sd = (sum((x-ma20)**2 for x in d[-20:])/20)**0.5
    up, lo = ma20+2*sd, ma20-2*sd
    print(nm, c, 'last', last, 'ma20dev', round((last/ma20-1)*100, 1),
          'boll%', round((last-lo)/(up-lo)*100, 1), 'up', round(up, 2), 'lo', round(lo, 2),
          'hi20dev', round((last/max(d[-20:])-1)*100, 1))
tdb.close()
