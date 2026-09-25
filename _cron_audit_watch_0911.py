#!/usr/bin/env python3
"""监督tick核查: 603036重复 + center_dual/fusion_center现金差。只读。"""
import sqlite3, json
from pathlib import Path
BASE = Path('/Users/zantao/.hermes/stockdb')
c = sqlite3.connect(str(BASE/'ledger.db'))

print('== 1. trade_log 603036 cmmr 全部记录 ==')
for r in c.execute("SELECT id,code,direction,price,quantity,amount,trade_date,trade_time,strategy FROM trade_log WHERE code='603036' AND strategy='cmmr'"):
    print(' ', r)

print('== 2. cmmr.json trades 里 603036 ==')
d = json.load(open(BASE/'sim_accounts/cmmr.json'))
for t in d.get('trades', []):
    if t.get('code') == '603036':
        print(' ', t)

print('== 3. center_dual / fusion_center 重建差值定位 ==')
for aid in ['center_dual', 'fusion_center']:
    d = json.load(open(BASE/f'sim_accounts/{aid}.json'))
    cash = d.get('initial_capital', 1000000.0)
    held = {}
    # 除权事件
    evs = []
    for code, exd, sh_add, net in c.execute("SELECT code, ex_date, shares_add, net_div FROM ca_adjustments WHERE account=? ORDER BY ex_date", (aid,)).fetchall():
        evs.append((str(exd).replace('-',''), '', 0, ('ca', code, int(sh_add or 0), float(net or 0))))
    for t in d.get('trades', []):
        evs.append((str(t.get('date','')).replace('-',''), str(t.get('trade_time','')), 1, ('t', t)))
    evs.sort(key=lambda x: (x[0], x[1], x[2]))
    delta_trace = []
    for _dn, _tt, _pri, payload in evs:
        if payload[0] == 'ca':
            _, code, sh_add, net = payload
            held[code] = held.get(code,0) + sh_add
            cash += net
            continue
        t = payload[1]
        code = t.get('code'); action = t.get('action'); shares = t.get('shares',0); price = t.get('price',0)
        if action == '买入':
            cash -= shares*price
            held[code] = held.get(code,0)+shares
        elif action == '卖出':
            cash += shares*price
            held[code] = held.get(code,0)-shares
        # 看trades条目是否带fee字段
    print(f'{aid}: 重建cash={cash:.2f} JSON cash={d.get("cash"):.2f} 差={cash-d.get("cash"):.2f}')
    # 检查trades里有没有fee/commission字段
    fee_keys = set()
    for t in d.get('trades', []):
        for k in t.keys():
            if 'fee' in k.lower() or 'comm' in k.lower() or 'cost' in k.lower():
                fee_keys.add(k)
    print(f'  trades中疑似费用字段: {fee_keys}')
    if fee_keys:
        total_fee = sum(t.get(k,0) or 0 for t in d.get('trades',[]) for k in fee_keys)
        print(f'  费用合计(所有key相加): {total_fee:.2f}')
    # 持仓比对
    json_held = {x['code']: x.get('shares',0) for x in d.get('positions',[])}
    mism = {code: (held.get(code,0), json_held.get(code,0)) for code in set(held)|set(json_held) if held.get(code,0)!=json_held.get(code,0)}
    print(f'  持仓不符: {mism if mism else "无"}')

print('== 4. ca_adjustments 近期记录 ==')
for r in c.execute("SELECT * FROM ca_adjustments ORDER BY ex_date DESC LIMIT 10"):
    print(' ', r)
c.close()
