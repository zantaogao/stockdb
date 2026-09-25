#!/usr/bin/env python3
"""收益反推除权还原的数学单测（复刻 daily_report/server_dashboard 反推段逻辑）
场景：10送10 + 10派5（factor=2, cash_div=0.5），持有 25 天税 20%：
  昨日 1000 股@昨收20 + 现金 50000 = 总资产 70000
  今日除权：2000 股，现金 +400（净息 1000×0.5×0.8）；今收=除权参考价 (20-0.5)/2=9.75
  真实当日收益 = 69900/70000-1 = -0.143%（仅亏税 100）
无还原时假亏 ≈ -22.7% → 证明还原必要性。
运行：cd ~/.hermes/stockdb && python3 -B scripts/_test_ca_reverse.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS = 0


def ok(name, cond, detail=''):
    global PASS
    print(f"  {'✅' if cond else '❌'} {name} {detail}")
    if cond:
        PASS += 1


def reverse_day(ca_map, pos_rows, cash_now, iso_buys_qty, iso_sells_qty, sell_income, buy_cost,
                prev_close, iso_close):
    """复刻 daily_report/dashboard 反推段：pos_rows=[(code,shares)]、买卖按股数 dict、
    sell_income/buy_cost 为金额（trade_log.amount）、ca_map={code:(factor,cash_div,tax_rate)}。
    返回 (昨日资产, 今日资产, 还原后昨日持仓, 还原后昨日现金)。"""
    yest_pos = {}
    for code, shares in pos_rows:
        yshares = shares - iso_buys_qty.get(code, 0) + iso_sells_qty.get(code, 0)
        if code in ca_map:
            f = ca_map[code][0]
            if f and f != 1.0:
                yshares = int(round(yshares / f))
        if yshares > 0:
            yest_pos[code] = yshares
    for code, sq in iso_sells_qty.items():
        if code not in yest_pos and code not in iso_buys_qty:
            yest_pos[code] = sq
            if code in ca_map:
                f = ca_map[code][0]
                if f and f != 1.0:
                    yest_pos[code] = int(round(sq / f))
    yest_cash = cash_now - sell_income + buy_cost
    for code, (f, cd, tr) in ca_map.items():
        if code in yest_pos:
            yest_cash -= yest_pos[code] * cd * (1 - tr)
    yest_asset = yest_cash
    for code, ys in yest_pos.items():
        yest_asset += ys * prev_close.get(code, 0)
    cur_asset = cash_now
    for code, sh in pos_rows:
        cur_asset += sh * iso_close.get(code, 0)
    return yest_asset, cur_asset, yest_pos, yest_cash


CA = {'A': (2.0, 0.5, 0.2)}  # 10送10+10派5 税20%
PREV = {'A': 20.0}           # 昨收（除权前）
CLOSE = {'A': 9.75}          # 今收 = 除权参考价 (20-0.5)/2


def scenario(name, pos_rows, cash_now, buys_qty, sells_qty, sell_income, buy_cost=0.0):
    ya, ca2, yp, yc = reverse_day(CA, pos_rows, cash_now, buys_qty, sells_qty,
                                  sell_income, buy_cost, PREV, CLOSE)
    ret = (ca2 / ya - 1) * 100
    print(f"\n== {name} ==")
    print(f"  还原后昨日: 持仓 {yp} 现金 {yc:,.0f} → 昨日资产 {ya:,.0f}")
    print(f"  今日资产 {ca2:,.0f} → 当日收益 {ret:+.3f}%")
    ok("昨日持仓还原为除权前 1000 股", yp.get('A') == 1000, f"实际 {yp.get('A')}")
    ok("昨日现金还原 50000（扣净息400）", abs(yc - 50000) < 0.01, f"实际 {yc:,.2f}")
    ok("昨日资产 = 70000", abs(ya - 70000) < 0.01, f"实际 {ya:,.2f}")
    ok(f"当日收益 = -0.143%（仅亏税）", abs(ret + 0.142857) < 0.001, f"实际 {ret:+.4f}%")
    return ya, ca2


def no_reverse_contrast():
    """对照：无还原（旧逻辑）→ 假亏 ≈ -22.7%"""
    ya_no, ca_no, _, _ = reverse_day({}, [('A', 2000)], 50400.0, {}, {}, 0.0, 0.0, PREV, CLOSE)
    ret_no = (ca_no / ya_no - 1) * 100
    print(f"\n== 对照：无除权还原（旧逻辑）==")
    print(f"  昨日资产(错) {ya_no:,.0f} → 当日收益 {ret_no:+.1f}% （假亏）")
    ok("旧逻辑假亏 ≈ -22.7%（证明还原必要）", ret_no < -20, f"实际 {ret_no:+.1f}%")


if __name__ == '__main__':
    print("场景 1：除权日无交易（持仓 2000 股 = 送转后）")
    scenario("无交易", [('A', 2000)], 50400.0, {}, {}, 0.0)
    print("\n场景 2：除权日卖出 500 股 @9.75（卖出的是送转后股份）")
    # 收入 500×9.75=4875；持仓剩 1500；现金 50400+4875=55275
    scenario("部分卖出", [('A', 1500)], 55275.0, {}, {'A': 500}, 4875.0)
    print("\n场景 3：除权日全清仓（卖 2000@9.75 收入 19500）")
    scenario("全清仓", [], 69900.0, {}, {'A': 2000}, 19500.0)
    no_reverse_contrast()
    TOTAL = 4 * 3 + 1
    print(f"\n结果: {PASS}/{TOTAL} 通过")
    sys.exit(0 if PASS == TOTAL else 1)
