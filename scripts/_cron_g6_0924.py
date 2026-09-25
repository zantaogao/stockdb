#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0924 第六轮：position_peaks 止盈线距离 + 策略账户持仓 R7 距离"""
import sqlite3, os, json
BASE = os.path.expanduser('~/.hermes/stockdb')
lc = sqlite3.connect(BASE + '/ledger.db'); lc.row_factory = sqlite3.Row
tabs = [r[0] for r in lc.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
out = {'tables': tabs}
try:
    pk = {r['code']: (r['peak_price'], r.get('peak_date') if 'peak_date' in r.keys() else None)
          for r in lc.execute("SELECT * FROM position_peaks").fetchall()}
except Exception as e:
    out['pk_err'] = str(e); pk = {}
holds = [dict(r) for r in lc.execute("SELECT * FROM holdings WHERE status='hold'").fetchall()]
risk = []
for h in holds:
    ac, close = h['avg_cost'], h['latest_price']
    sl = h['stop_loss'] or 0
    sl_eff = min(sl, ac * 0.94) if sl else 0
    row = dict(code=h['code'], name=h['name'], ac=ac, close=close, sl=sl,
               sl_eff=round(sl_eff, 3), sl_gap=round((close / sl_eff - 1) * 100, 2) if sl_eff else None)
    p = pk.get(h['code'])
    if p:
        peak = p[0]
        if peak and ac and peak >= 1.05 * ac:
            line = peak * 0.92
            row.update(peak=round(peak, 2), tp_line=round(line, 2), tp_gap=round((close / line - 1) * 100, 2))
    risk.append(row)
out['main_risk'] = risk
# 策略账户持仓
try:
    sh = [dict(r) for r in lc.execute("SELECT * FROM strategy_holdings").fetchall()]
except Exception:
    try:
        sh = [dict(r) for r in lc.execute("SELECT * FROM strategy_accounts_holdings").fetchall()]
    except Exception as e:
        sh = []; out['sh_err'] = str(e)
out['sh_cols'] = list(sh[0].keys()) if sh else None
r7 = []
for r in sh:
    ac = r.get('avg_cost') or r.get('cost')
    px = r.get('latest_price') or r.get('current_price')
    if ac and px:
        gap = (px / (ac * 0.94) - 1) * 100
        r7.append((r.get('account_id'), r.get('code'), r.get('name'), round(ac, 2), round(px, 2), round(gap, 2)))
r7.sort(key=lambda x: x[5])
out['r7_bottom'] = r7[:12]
out['r7_hits'] = [x for x in r7 if x[5] <= 0]
lc.close()
print(json.dumps(out, ensure_ascii=False, default=str, indent=1))
