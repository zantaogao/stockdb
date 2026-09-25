#!/usr/bin/env /usr/bin/python3 -B
"""规则5C 离线验证（不下单不写库）：直接调 check_sell_conditions
用例：301557 常友（32天 fusion -2.5 → 应触发）、688636 智明达（34天 fusion +6.2 → 不触发）、
fusion=None（不误杀）、29天 fusion -2（未到期不触发）、5B优先场景（25天 final<30 盈亏<8 → 走5B不走5C）"""
import sys, sqlite3
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from scripts.intraday_decision import check_sell_conditions

sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
def fus(code):
    r = sig.execute("""SELECT fusion_score FROM signal_history WHERE stock_code=?
        AND REPLACE(date,'-','')=(SELECT MAX(REPLACE(date,'-','')) FROM signal_history)""", (code,)).fetchone()
    return r[0] if r else None

cases = [
    ('301557', dict(avg_cost=72.7, shares=100, buy_date='2026-08-03', target_price=95.17, stop_loss=76.4, peak_price=83.0), 83.0, 24.4, fus('301557'), '应触发5C'),
    ('688636', dict(avg_cost=16.54, shares=100, buy_date='2026-07-30', target_price=21.87, stop_loss=17.22, peak_price=19.97), 19.97, 98.5, fus('688636'), 'fusion正,不应触发'),
    ('600000', dict(avg_cost=10, shares=1000, buy_date='2026-08-01', target_price=12, stop_loss=9, peak_price=10.5), 10.5, 60, None, 'fusion=None不误杀'),
    ('600001', dict(avg_cost=10, shares=1000, buy_date='2026-08-11', target_price=12, stop_loss=9, peak_price=10.5), 10.5, 60, -2.0, '29交易日内外,不应触发5C'),
    ('600002', dict(avg_cost=10, shares=1000, buy_date='2026-08-18', target_price=12, stop_loss=9, peak_price=10.2), 10.1, 25, -1.0, '20余天盈亏<8走5B'),
]
for code, pos, price, score, f, note in cases:
    r = check_sell_conditions(code, pos, price, score, 0.0, fusion_score=f)
    print(f"{code} fusion={f} → {r}  | 预期: {note}")
