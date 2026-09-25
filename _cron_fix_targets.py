#!/usr/bin/env python3
"""持仓目标价/止损修复 (2026-08-27; 2026-08-28 加可达性约束)
问题: 600508 target=0(规则2止盈失效), 688636 target=48.35(MAX聚合捞回7/24异常值, 正确21.87),
      600363/603093/688501 target=ma20+2σ 在均线高于现价的下跌趋势票上永远够不着(1.4-1.7倍现价,
      规则2达目标价止盈失效)。
修复: 对全部持仓重算目标价 = min(ma20+2σ, 现价×1.25)（可达性约束, 2026-08-28 用户拍板 B 方案）
      + max(ma20-2σ, 现价×0.88) 止损,
      仅在现持仓值与重算值偏差>15%或缺失时更新(不覆盖正常值)。
只写 state.db holdings。
"""
import sqlite3, duckdb
import numpy as np

STATE = '/Users/zantao/.hermes/stockdb/state.db'
TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'

s = sqlite3.connect(STATE)
d = duckdb.connect(TUSHARE, read_only=True)

rows = s.execute("SELECT code, avg_cost, latest_price, target_price, stop_loss FROM holdings WHERE status='hold'").fetchall()
print(f"{'code':<8} {'现target':<10} {'重算target':<10} {'现止损':<9} {'重算止损':<9} {'动作'}")
changed = []
for code, cost, price, tp, sl in rows:
    cost = float(cost); price = float(price)
    ts = f"{code}.SH" if code.startswith(('6', '68', '9')) else f"{code}.SZ"
    cls = [r[0] for r in d.execute(
        "SELECT close FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 60", [ts]).fetchall()]
    if len(cls) < 20:
        continue
    cls = cls[::-1]
    ma20 = float(np.mean(cls[-20:]))
    std20 = float(np.std(cls[-20:], ddof=1))
    # 2026-08-28 B 方案: 目标价加可达性约束（均线高于现价时 ma20+2σ 永远够不着）
    new_tp = round(min(ma20 + 2 * std20, price * 1.25), 2)
    new_sl = round(max(ma20 - 2 * std20, price * 0.88), 2)
    # 判定: target 缺失(=0)或偏差>15%; 止损偏差>15%
    tp_fix = (tp is None or float(tp) == 0 or abs(float(tp) - new_tp) / new_tp > 0.15)
    sl_fix = (sl is None or float(sl) == 0 or abs(float(sl) - new_sl) / new_sl > 0.15)
    act = []
    if tp_fix:
        act.append(f"target {tp}→{new_tp}")
    if sl_fix:
        act.append(f"止损 {sl}→{new_sl}")
    if act:
        s.execute("UPDATE holdings SET target_price=?, stop_loss=? WHERE code=?",
                  (new_tp if tp_fix else tp, new_sl if sl_fix else sl, code))
        changed.append(code)
        print(f"{code:<8} {str(tp):<10} {new_tp:<10.2f} {str(sl):<9} {new_sl:<9.2f} {'、'.join(act)}")
    else:
        print(f"{code:<8} {str(tp):<10} {new_tp:<10.2f} {str(sl):<9} {new_sl:<9.2f} 正常不动")

s.commit()
print(f"\n修复 {len(changed)} 只: {changed}")
s.close(); d.close()
