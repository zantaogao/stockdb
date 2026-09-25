#!/usr/bin/env python3
"""复核 _ic_scope_audit_0906.py：逐日Top10(我的复现口径) vs ic_window官方列(产线口径)。
对得上（≤0.01舍入差）→ 审计子集定义/价格/过滤与产线一致。"""
import sqlite3
import duckdb
import numpy as np

st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
td = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)

tdays = [str(r[0]) for r in td.execute(
    "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
tidx = {d: i for i, d in enumerate(tdays)}

bad = set()
for r in st.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    sc, nm, mk = r
    if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(sc).startswith(('8', '4', '92')):
        bad.add(sc)

def code_to_ts(c):
    return c + ('.SH' if c.startswith(('6', '9')) else '.SZ')

dates = [str(r[0]).replace('-', '') for r in st.execute(
    "SELECT DISTINCT signal_date FROM ic_window ORDER BY 1").fetchall()]
print('信号日 | 我的cmmr20 官方cmmr20 | 我的cmmrf20 官方cmmrf20 | 我的main20 官方main20')
mism = 0
for sd in dates:
    row = st.execute(
        "SELECT fwd20_top_cmmr, fwd20_top_cmmrf, fwd20_top_main FROM ic_window WHERE signal_date=?",
        (f'{sd[:4]}-{sd[4:6]}-{sd[6:]}',)).fetchone()
    if row is None:
        row = st.execute(
            "SELECT fwd20_top_cmmr, fwd20_top_cmmrf, fwd20_top_main FROM ic_window WHERE signal_date=?",
            (sd,)).fetchone()
    if row is None or tidx.get(sd) is None or tidx[sd] + 20 >= len(tdays):
        continue
    end = tdays[tidx[sd] + 20]
    sig = st.execute(
        "SELECT stock_code, fusion_score, cmmr_score, fusion_score_cmmr FROM signal_history "
        "WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL", (sd,)).fetchall()
    p0 = {r[0]: float(r[1]) for r in td.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (sd,)).fetchall()}
    p1 = {r[0]: float(r[1]) for r in td.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (end,)).fetchall()}
    recs = []
    for code, fus, cmmr, cmmrf in sig:
        tc = code_to_ts(code)
        if code in bad or tc not in p0 or tc not in p1 or p0[tc] <= 0 or p1[tc] <= 0:
            continue
        recs.append((code, float(fus or 0), float(cmmr or 0), float(cmmrf or 0),
                     (p1[tc] / p0[tc] - 1) * 100))
    if len(recs) < 100:
        continue

    def top10(idx, positive=False, pct85=False):
        items = [(r[0], r[idx], r[4]) for r in recs]
        if positive:
            items = [x for x in items if x[1] > 0]
        if pct85 and items:
            scs = sorted(x[1] for x in items)
            th = scs[int(len(scs) * 0.85)]
            items = [x for x in items if x[1] >= th]
        items.sort(key=lambda x: x[1], reverse=True)
        t = [x[2] for x in items[:10]]
        return round(sum(t) / len(t), 3) if t else None

    mine = (top10(2, positive=True),        # cmmr 20d
            top10(3, positive=True, pct85=True),  # cmmrf 20d
            top10(1))                        # main 20d
    offs = [abs(a - b) if a is not None and b is not None else -1
            for a, b in zip(mine, row)]
    flag = 'OK' if all(o <= 0.011 for o in offs if o >= 0) else 'MISMATCH'
    if flag != 'OK':
        mism += 1
    print('%s | %8.3f %8.3f | %8.3f %8.3f | %8.3f %8.3f  %s' % (
        sd, mine[0] if mine[0] is not None else float('nan'), row[0] if row[0] is not None else float('nan'),
        mine[1] if mine[1] is not None else float('nan'), row[1] if row[1] is not None else float('nan'),
        mine[2] if mine[2] is not None else float('nan'), row[2] if row[2] is not None else float('nan'), flag))
print('不一致天数:', mism)