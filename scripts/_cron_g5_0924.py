#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0924 第五轮：持仓逐票当日贡献/累计/风控距离 + 中枢自算IC + center_dual 5日"""
import sqlite3, duckdb, os, json
BASE = os.path.expanduser('~/.hermes/stockdb')
lc = sqlite3.connect(BASE + '/ledger.db'); lc.row_factory = sqlite3.Row
holds = [dict(r) for r in lc.execute("SELECT * FROM holdings").fetchall()]
tdb = duckdb.connect(BASE + '/tushare.db', read_only=True)

out = {'holds': [], 'risk': {}}
tot = sum(h['shares'] * h['latest_price'] for h in holds)
out['total_pos_value'] = round(tot, 2)
rows = []
for h in holds:
    ts = h['code'] + ('.SH' if h['code'].startswith(('6', '5', '9')) else '.SZ')
    d = tdb.execute("SELECT trade_date, close, pct_chg FROM daily WHERE ts_code=? AND trade_date>='20260918' ORDER BY trade_date", (ts,)).fetchall()
    prev = d[-2][1] if len(d) >= 2 else None
    day_pnl = (h['latest_price'] - prev) * h['shares'] if prev else None
    tgt_gap = (h['target_price'] / h['latest_price'] - 1) * 100 if h.get('target_price') else None
    sl_gap = (h['latest_price'] / h['stop_loss'] - 1) * 100 if h.get('stop_loss') else None
    rows.append(dict(code=h['code'], name=h['name'], shares=h['shares'], cost=h['avg_cost'],
                     px=h['latest_price'], pnl=h['pnl'], pnl_pct=h['pnl_pct'],
                     day=round(d[-1][2], 2) if d else None, day_pnl=round(day_pnl) if day_pnl is not None else None,
                     mv=round(h['shares'] * h['latest_price']),
                     tgt_gap=round(tgt_gap, 2) if tgt_gap is not None else None,
                     sl_gap=round(sl_gap, 2) if sl_gap is not None else None,
                     r5=[round(x[2], 2) for x in d[-5:]]))
rows.sort(key=lambda r: (r['day_pnl'] if r['day_pnl'] is not None else 0))
out['holds'] = rows
# 风控集中敞口
out['near_tgt'] = [r for r in rows if r['tgt_gap'] is not None and r['tgt_gap'] < 5]
out['near_sl'] = [r for r in rows if r['sl_gap'] is not None and r['sl_gap'] < 3]
out['near_tgt_sum'] = sum(r['mv'] for r in out['near_tgt'])
out['near_sl_sum'] = sum(r['mv'] for r in out['near_sl'])

# 中枢分 次日 / 10日 IC 自算
sc = sqlite3.connect(BASE + '/signals.db')
days = [r[0] for r in sc.execute("SELECT DISTINCT REPLACE(date,'-','') d FROM fusion_center_signals ORDER BY d DESC LIMIT 7").fetchall()]
def rank_ic(pairs):
    if len(pairs) < 50: return None
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i]); rk = [0]*len(v)
        for pos, i in enumerate(order): rk[i] = pos
        return rk
    a = rank([p[0] for p in pairs]); b = rank([p[1] for p in pairs]); n = len(pairs)
    ma, mb = sum(a)/n, sum(b)/n
    cov = sum((a[i]-ma)*(b[i]-mb) for i in range(n))
    va = sum((x-ma)**2 for x in a)**0.5; vb = sum((x-mb)**2 for x in b)**0.5
    return round(cov/(va*vb), 4) if va and vb else None

res = []
for sd in days:
    cs = dict(sc.execute("SELECT stock_code, score FROM fusion_center_signals WHERE REPLACE(date,'-','')=? AND score IS NOT NULL", (sd,)).fetchall())
    cs = {k.split('.')[0]: v for k, v in cs.items()}
    nxt = tdb.execute("SELECT trade_date FROM daily WHERE trade_date>? ORDER BY trade_date LIMIT 1", (sd,)).fetchone()
    if not nxt: continue
    nd = nxt[0]
    p0 = {r[0][:6]: r[1] for r in tdb.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (sd,)).fetchall()}
    p1 = {r[0][:6]: r[1] for r in tdb.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (nd,)).fetchall()}
    pairs = [(cs[c], p1[c]/p0[c]-1) for c in cs if c in p0 and c in p1 and p0[c] > 0]
    res.append((sd, nd, rank_ic(pairs), len(pairs)))
out['center_ic_self'] = res
out['center_dual_ic'] = sc.execute("SELECT date, ROUND(ic,4) FROM center_dual_ic_daily ORDER BY date DESC LIMIT 6").fetchall()
sc.close(); tdb.close(); lc.close()
print(json.dumps(out, ensure_ascii=False, default=str, indent=1))
