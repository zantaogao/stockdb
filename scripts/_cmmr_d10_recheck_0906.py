#!/usr/bin/env python3
"""复核 cmmr 全截面 D10 = +0.00 的逐日明细。"""
import sqlite3, duckdb, numpy as np
st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
td = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
tdays = [str(r[0]) for r in td.execute("SELECT DISTINCT trade_date FROM daily ORDER BY 1").fetchall()]
tidx = {d: i for i, d in enumerate(tdays)}
sig_dates = [str(r[0]) for r in st.execute(
    "SELECT DISTINCT REPLACE(date,'-','') FROM signal_history ORDER BY 1").fetchall()]
mature = [d for d in sig_dates if d in tidx and tidx[d] + 20 < len(tdays)]
bad = set()
for sc, nm, mk in st.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(sc).startswith(('8', '4', '92')):
        bad.add(str(sc))
for sd in mature:
    end = tdays[tidx[sd] + 20]
    sig = st.execute("SELECT stock_code, cmmr_score FROM signal_history WHERE REPLACE(date,'-','')=?", (sd,)).fetchall()
    if not sig:
        print(sd, 'no signal rows'); continue
    p0 = {r[0]: float(r[1]) for r in td.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (sd,)).fetchall()}
    p1 = {r[0]: float(r[1]) for r in td.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (end,)).fetchall()}
    data = []
    for code, cs in sig:
        ts = code + ('.SH' if code.startswith(('6', '9')) else '.SZ')
        if ts in p0 and ts in p1 and p0[ts] > 0 and code not in bad:
            data.append((float(cs or 0), (p1[ts] / p0[ts] - 1) * 100))
    if len(data) < 20:
        print(sd, 'skip n=', len(data)); continue
    data.sort()
    n = len(data)
    d10 = data[9 * n // 10:]
    mret = np.mean([(p1[t] / p0[t] - 1) * 100 for t in p0 if t in p1 and t[:6] not in bad and p0[t] > 0])
    print(sd, f'n={n} D10n={len(d10)} 原始={np.mean([v for _, v in d10]):+.2f}% 市场={mret:+.2f}% 超额={np.mean([v for _, v in d10]) - mret:+.2f}% 分界{d10[0][0]:.1f}~{d10[-1][0]:.1f}')