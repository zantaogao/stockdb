#!/usr/bin/env python3
"""audit（_cron_daily_audit.py）除权适配的数学验证
复制其模块3（重建回放）/模块6（双向核对）同构逻辑，验证：
  A. 送转后：持仓>累计买入 不再误报幽灵；重放现金/持仓对齐
  B. 真幽灵（无买入有持仓）仍被抓
  C. 除权后卖出超原始累计买入 不再误报"卖出超持仓"
运行：cd ~/.hermes/stockdb && python3 -B scripts/_test_ca_audit.py
"""
import sys, json, tempfile, os, shutil
from pathlib import Path
from collections import defaultdict

PASS = 0


def ok(name, cond, detail=''):
    global PASS
    print(f"  {'✅' if cond else '❌'} {name} {detail}")
    if cond:
        PASS += 1


INIT = 1000000.0


def replay(aid, trades, ca_rows, json_cash, json_held):
    """同构 _cron_daily_audit.py 模块3：trades + ca 事件归并重放。返回 (issues, held, cash)"""
    issues = []
    cash = INIT
    held = {}
    ca_events = [(str(exd).replace('-', ''), ('ca', code, int(sh_add or 0), float(net or 0)))
                 for code, exd, sh_add, net in ca_rows]
    ev_stream = [(str(t.get('date', '')).replace('-', ''), ('t', t)) for t in trades] + ca_events
    ev_stream.sort(key=lambda x: (x[0], 0 if x[1][0] == 'ca' else 1))
    for _dn, payload in ev_stream:
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
            if held.get(code, 0) < shares:
                issues.append(f"卖出超持仓: {code}")
            held[code] = held.get(code, 0) - shares
    if abs(cash - json_cash) > 1:
        issues.append(f"现金不符: 重建{cash:.0f} vs JSON{json_cash:.0f}")
    for code in set(held) | set(json_held):
        if held.get(code, 0) != json_held.get(code, 0):
            issues.append(f"持仓不符: {code} 重建{held.get(code,0)} vs JSON{json_held.get(code,0)}")
    return issues, held, cash


def check_ghost(aid, trades, ca_qty, positions):
    """同构模块6 方向二：幽灵持仓判定。ca_qty = {code: 送转累计}"""
    issues = []
    buy_qty = defaultdict(int)
    for t in trades:
        if t.get('action') == '买入':
            buy_qty[t.get('code')] += t.get('shares', 0)
    for x in positions:
        code = x.get('code')
        if code not in buy_qty or buy_qty[code] <= 0:
            issues.append(f"幽灵(无买入): {code}")
        elif buy_qty[code] + ca_qty.get(code, 0) < x.get('shares', 0):
            issues.append(f"幽灵(超累计): {code} 持仓{x.get('shares')} > 买{buy_qty[code]}+送{ca_qty.get(code,0)}")
    return issues


def t_buy(date, code, shares, price=20.0):
    return {'date': date, 'action': '买入', 'code': code, 'shares': shares, 'price': price}


def t_sell(date, code, shares, price=10.0):
    return {'date': date, 'action': '卖出', 'code': code, 'shares': shares, 'price': price}


if __name__ == '__main__':
    print("场景 A：送转（10送10+派息）后账户状态 → 重建应零告警")
    # trades: 9/1 买 1000@20 (成本 20000)；ca: 9/4 送转 +1000 净息 +400；9/5 卖 1500@10
    # 现金: 1000000-20000+400+15000 = 995400；持仓: 1000+1000-1500 = 500
    trades = [t_buy('20260901', '300001', 1000), t_sell('20260905', '300001', 1500)]
    ca_rows = [('300001', '20260904', 1000, 400.0)]
    issues, held, cash = replay('cmmr', trades, ca_rows, 995400.0, {'300001': 500})
    ok("A1 送转后重放无告警", not issues, f"{issues}")
    ok("A2 重放持仓 500", held.get('300001') == 500, f"{held}")
    ok("A3 重放现金对齐", abs(cash - 995400) < 0.01, f"{cash}")

    print("场景 B：送转后 '持仓>累计买入' 不误报幽灵，真幽灵仍抓")
    trades_b = [t_buy('20260901', '300001', 1000)]
    ca_qty = {'300001': 1000}
    pos_b = [{'code': '300001', 'shares': 2000}, {'code': '688888', 'shares': 300}]  # 送转 2000 + 真幽灵 688888
    iss_b = check_ghost('fusion3f', trades_b, ca_qty, pos_b)
    ok("B1 送转股不报幽灵", not any('300001' in i for i in iss_b), f"{iss_b}")
    ok("B2 真幽灵仍被抓", any('688888' in i for i in iss_b), f"{iss_b}")
    # 无 ca_qty 时（旧逻辑）应误报
    iss_old = check_ghost('fusion3f', trades_b, {}, [{'code': '300001', 'shares': 2000}])
    ok("B3 对照：无 ca 适配会误报（证明必要性）", any('300001' in i for i in iss_old), f"{iss_old}")

    print("场景 C：除权日卖出不超持仓（重放含送转事件）")
    # 买 1000 → 送转 +1000 → 卖 1500（≤2000）不应报超卖；若无 ca 事件则报超卖
    iss_c = replay('cmmr', trades, ca_rows, 995400.0, {'300001': 500})[0]
    ok("C1 含 ca 事件不报卖出超持仓", not any('卖出超持仓' in i for i in iss_c), f"{iss_c}")
    iss_c2 = replay('cmmr', trades, [], 995400.0, {'300001': 500})[0]
    ok("C2 对照：无 ca 事件会报卖出超持仓（证明必要性）", any('卖出超持仓' in i for i in iss_c2), f"{iss_c2}")

    print("场景 D：纯派息（factor=1 无增股）现金对齐")
    trades_d = [t_buy('20260901', '300001', 1000)]
    ca_d = [('300001', '20260904', 0, 800.0)]
    issues_d, held_d, cash_d = replay('cmmr', trades_d, ca_d, 1000000 - 20000 + 800, {'300001': 1000})
    ok("D1 纯派息无告警", not issues_d, f"{issues_d}")
    ok("D2 持仓不变 1000", held_d.get('300001') == 1000)

    TOTAL = 10
    print(f"\n结果: {PASS}/{TOTAL} 通过")
    sys.exit(0 if PASS == TOTAL else 1)
