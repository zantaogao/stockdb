#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cron 午间报告：主账户上午盈亏 + 有效止损距离（只读）"""
import sys, sqlite3
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))
from core.prices import _fetch_sina
import duckdb

PREV = '20260911'
d = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
prev_close = {}
con = sqlite3.connect(str(BASE / 'ledger.db'))
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute('SELECT * FROM holdings')]
cash = con.execute("SELECT cash_balance FROM account_balance WHERE account_id='main'").fetchone()[0]
pos = position = con.execute('SELECT * FROM position_peaks').fetchall()
con.close()
peaks = {r[0]: r[1] for r in pos}

codes = [str(h['code']) for h in rows]
for c in codes:
    ts = c + ('.SH' if c.startswith(('6', '9')) else '.SZ')
    r = d.execute('SELECT close FROM daily WHERE ts_code=? AND trade_date=?', [ts, PREV]).fetchone()
    prev_close[c] = r[0] if r else None
d.close()

q = _fetch_sina(codes)
print('%-8s %-8s %8s %8s %8s %8s %8s %8s' % ('code', 'name', '成本', '周五收', '现价', '今涨%', '浮盈%', '上午盈亏元'))
tot_prev_val = 0.0
tot_now_val = 0.0
for h in rows:
    c = str(h['code'])
    px = (q.get(c) or {}).get('price')
    pc = prev_close.get(c)
    sh = h['shares']
    if not px:
        print('%s 无实时价' % c)
        continue
    tot_prev_val += sh * pc
    tot_now_val += sh * px
    delta = sh * (px - pc)
    # 执行端有效止损 = min(扫描止损, 成本×0.94)
    eff = None
    if h['stop_loss'] and h['avg_cost']:
        eff = min(h['stop_loss'], h['avg_cost'] * 0.94)
    pk = peaks.get(c)
    dd = (px / pk - 1) * 100 if pk else None
    print('%-8s %-8s %8.2f %8.2f %8.2f %+8.2f %+8.2f %+10.0f  有效止损=%.2f 距%+.1f%%  峰值回撤%s' % (
        c, (h['name'] or '')[:6], h['avg_cost'], pc, px, (px / pc - 1) * 100,
        (px / h['avg_cost'] - 1) * 100, delta, eff if eff else 0,
        (px / eff - 1) * 100 if eff else 0,
        ('%.1f%%' % dd) if dd is not None else '-'))

print('\n持仓市值(周五收) %.0f → (现) %.0f 变化 %+.0f 元 (%.2f%%)' % (
    tot_prev_val, tot_now_val, tot_now_val - tot_prev_val,
    (tot_now_val / tot_prev_val - 1) * 100))
tot_prev = cash + tot_prev_val
tot_now = cash + tot_now_val
print('账户总资产 %.0f → %.0f (%+.0f 元, %+.2f%%)  现金 %.0f (%.1f%%)' % (
    tot_prev, tot_now, tot_now - tot_prev, (tot_now / tot_prev - 1) * 100, cash, cash / tot_now * 100))
