#!/usr/bin/env python3
"""查主账户持仓止盈距离：收益排序 + R2/R3 触发价"""
import sys, sqlite3
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.hermes' / 'stockdb'))

from core.hold_days import calc_holding_days

BASE = Path.home() / '.hermes' / 'stockdb'
c = sqlite3.connect(str(BASE / 'state.db'))

# 持仓 + peak
rows = c.execute("""
    SELECT h.code, h.name, h.shares, h.avg_cost, h.buy_date, h.target_price, h.stop_loss,
           COALESCE(p.peak_price, h.avg_cost)
    FROM holdings h LEFT JOIN position_peaks p ON p.code = h.code
    WHERE h.status='hold'
""").fetchall()

# 实时价
from core.prices import fetch_price_live

results = []
for code, name, shares, cost, buy_date, target, stop, peak in rows:
    price, chg = fetch_price_live(code)
    if not price:
        price = 0
    pnl = (price / cost - 1) * 100 if cost else 0
    hold_days = calc_holding_days(buy_date)
    # R2 达目标价：price >= target 且 hold>=5
    r2_gap = None
    if target and target > 0 and hold_days >= 5:
        r2_gap = (target / price - 1) * 100 if price else None  # 还需涨多少%
    # R3 回撤止盈：peak >= cost*1.05 且 price <= peak*0.92
    r3_active = peak >= cost * 1.05
    r3_trigger = peak * 0.92 if r3_active else None
    r3_gap = (price / r3_trigger - 1) * 100 if r3_trigger else None  # 距触发还有多少%空间
    results.append({
        'code': code, 'name': name, 'cost': cost, 'price': price,
        'pnl': pnl, 'buy_date': buy_date, 'hold_days': hold_days,
        'target': target or 0, 'peak': peak, 'r3_active': r3_active,
        'r3_trigger': r3_trigger, 'r3_gap': r3_gap, 'r2_gap': r2_gap,
    })
c.close()

# 按收益降序
results.sort(key=lambda x: -x['pnl'])
print(f"{'代码':<8}{'名称':<8}{'成本':>7}{'现价':>7}{'收益%':>7}{'持有':>4}{'峰值':>7}{'目标价':>7}  R3触发价/空间   R2还需涨")
for r in results:
    r3 = f"{r['r3_trigger']:.2f}/{r['r3_gap']:+.1f}%" if r['r3_active'] and r['r3_gap'] is not None else "未激活"
    r2 = f"{r['r2_gap']:+.1f}%" if r['r2_gap'] is not None else "-"
    print(f"{r['code']:<8}{r['name']:<8}{r['cost']:>7.2f}{r['price']:>7.2f}{r['pnl']:>+7.1f}{r['hold_days']:>4}{r['peak']:>7.2f}{r['target']:>7.2f}  {r3:<16} {r2}")

print()
print("=== 收益 >= 20% 的持仓详细解读 ===")
for r in results:
    if r['pnl'] >= 20:
        print(f"\n{r['code']} {r['name']} 收益{r['pnl']:+.1f}% 成本{r['cost']:.2f} 现价{r['price']:.2f} 峰值{r['peak']:.2f} 持有{r['hold_days']}天")
        if r['r3_active'] and r['r3_trigger']:
            print(f"  R3回撤止盈已激活: 现价跌到 {r['r3_trigger']:.2f} (峰值{r['peak']:.2f}×0.92, 距现价{r['r3_gap']:+.1f}%) 触发卖出")
            print(f"  即: 从现价{r['price']:.2f}再跌 {abs(r['r3_gap']):.1f}% 就落袋")
        if r['r2_gap'] is not None:
            print(f"  R2达目标价: 涨到 {r['target']:.2f} (还需{r['r2_gap']:+.1f}%) 且已持{r['hold_days']}天≥5 → 卖出")
        elif r['target'] > 0 and r['hold_days'] < 5:
            print(f"  R2达目标价: 目标{r['target']:.2f} 但持有{r['hold_days']}天<5, 未满足")
        else:
            print(f"  无目标价设置(R2不适用), 只走R3回撤止盈")
