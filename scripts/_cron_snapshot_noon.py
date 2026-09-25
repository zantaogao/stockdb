#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cron 午间报告：实时快照（主账户持仓 + 指数 + 今日成交）— 只读，不下单"""
import sys, sqlite3, json
from pathlib import Path
from datetime import datetime

BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))
from core.prices import _fetch_sina

print('时间:', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

# 指数
idx = {'000001': '上证指数', '399001': '深证成指', '399006': '创业板指', '000852': '中证1000'}
d = _fetch_sina(list(idx.keys()))
for c, n in idx.items():
    v = d.get(c)
    if not v:
        print('  %s 无数据' % n)
        continue
    p, pv, op = v['price'], v['prev'], v['open']
    print('  %-6s %10.2f  %+.2f%%  (昨收 %.2f 今开 %+.2f%%)' % (
        n, p, (p / pv - 1) * 100, pv, (op / pv - 1) * 100 if op and pv else 0))

# 主账户持仓
con = sqlite3.connect(str(BASE / 'ledger.db'))
con.row_factory = sqlite3.Row
cols = [r[1] for r in con.execute('PRAGMA table_info(holdings)')]
print('\nholdings 列:', cols)
rows = con.execute('SELECT * FROM holdings').fetchall()
holdings = [dict(r) for r in rows]
codes = [str(h.get('stock_code') or h.get('code')) for h in holdings]
prices = _fetch_sina(codes)
print('\n=== 主账户持仓 ===')
for h in holdings:
    c = str(h.get('stock_code') or h.get('code'))
    px = (prices.get(c) or {}).get('price')
    cost = h.get('avg_cost') or h.get('cost')
    sl = h.get('stop_loss')
    tg = h.get('target_price') or h.get('target')
    sh = h.get('shares') or h.get('quantity')
    line = '%s %-8s px=%s cost=%s sh=%s' % (c, h.get('stock_name') or '', px, cost, sh)
    if cost and px:
        line += ' pnl=%+.1f%%' % ((px / cost - 1) * 100)
    if sl and px:
        line += ' 止损%s 距%+.1f%%' % (sl, (px / sl - 1) * 100)
    if tg and px:
        line += ' 目标%s 距%+.1f%%' % (tg, (px / tg - 1) * 100)
    print(' ', line)

# 今日成交
print('\n=== trade_log 今日 ===')
tcols = [r[1] for r in con.execute('PRAGMA table_info(trade_log)')]
print('列:', tcols)
try:
    for r in con.execute("SELECT * FROM trade_log ORDER BY rowid DESC LIMIT 8"):
        print(' ', dict(r))
except Exception as e:
    print(' err', e)

print('\n=== account_balance ===')
for r in con.execute('SELECT * FROM account_balance'):
    print(' ', dict(r))
con.close()
