#!/usr/bin/env python3
"""探测 09-10 对账报警根因: center_dual 差6 / fusion_center 差328。只读。"""
import sqlite3, json
from collections import defaultdict
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb')
c = sqlite3.connect(str(BASE / 'ledger.db'))
SIM = BASE / 'sim_accounts'
INIT = 1000000.0

for aid, report_diff in [('center_dual', 6), ('fusion_center', 328)]:
    d = json.load(open(SIM / f'{aid}.json'))
    print(f'==== {aid}: JSON cash={d.get("cash"):.2f} initial={d.get("initial_capital", INIT)}')
    # 重放并记录每步现金,找差值引入点
    evs = []
    for code, exd, sh_add, net in c.execute(
            "SELECT code, ex_date, shares_add, net_div FROM ca_adjustments WHERE account=? ORDER BY ex_date",
            (aid,)).fetchall():
        evs.append((str(exd).replace('-', ''), '', 0, ('ca', code, int(sh_add or 0), float(net or 0))))
    for i, t in enumerate(d.get('trades', [])):
        evs.append((str(t.get('date', '')).replace('-', ''), str(t.get('trade_time', '')), 1, ('t', t)))
    evs.sort(key=lambda x: (x[0], x[1], x[2]))
    cash = d.get('initial_capital', INIT)
    held = {}
    for _dn, _tt, _pri, payload in evs:
        if payload[0] == 'ca':
            _, code, sh_add, net = payload
            held[code] = held.get(code, 0) + sh_add
            cash += net
            continue
        t = payload[1]
        code = t.get('code'); action = t.get('action'); shares = t.get('shares', 0); price = t.get('price', 0)
        if action == '买入':
            cash -= shares * price
            held[code] = held.get(code, 0) + shares
        elif action == '卖出':
            cash += shares * price
            held[code] = held.get(code, 0) - shares
    print(f'  重放终点现金 = {cash:.2f}, 与JSON差 = {cash - d.get("cash", 0):.2f}')
    # 逐笔看 JSON trades 里是否带 fee/commission 字段
    keys = set()
    for t in d.get('trades', []):
        keys |= set(t.keys())
    print('  trade字段:', sorted(keys))
    # 最近10笔
    print('  最近交易(JSON trades 末尾):')
    for t in d.get('trades', [])[-10:]:
        print('   ', t)
    # ca_adjustments 该账户全部
    print('  ca_adjustments:')
    for r in c.execute("SELECT * FROM ca_adjustments WHERE account=?", (aid,)).fetchall():
        print('   ', r)
    # 该策略 trade_log 最近条目
    print('  trade_log 最近5条:')
    for r in c.execute("SELECT trade_date,trade_time,code,direction,price,quantity,amount FROM trade_log WHERE strategy=? ORDER BY REPLACE(trade_date,'-',''),trade_time,id DESC LIMIT 5", (aid,)).fetchall():
        print('   ', r)
print('\nca_adjustments schema:', [r[1] for r in c.execute("PRAGMA table_info(ca_adjustments)").fetchall()])
c.close()