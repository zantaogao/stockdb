#!/usr/bin/env python3
"""09-11 除权派息补账：修复 DB-first 迁移后被 strategy_accounts_daily save 抹掉的两笔除息。
背景：adjust_corporate_action.py 当时只写 JSON，cash 权威源 DB(meta) 没动 → 下一轮 save 用 DB 旧值盖回 JSON。
本脚本把派息同时补进 DB 与 JSON（对账重建=JSON trades 重放+ca表，两边必须一致）。
300818 已卖出：只补 center_dual 现金 +6.4。
301055 在持仓：fusion_center 现金 +328，持仓 avg_cost/peak/stop 按除权参考价 (v-cash_div)/factor 回调。
"""
import sqlite3, json
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb')
con = sqlite3.connect(BASE / 'ledger.db')

# ── center_dual +6.4（300818 9/8 除息，票已 9/10 卖出，仅现金腿） ──
row = con.execute("SELECT cash FROM strategy_accounts_meta WHERE account_id='center_dual'").fetchone()
assert row and abs(row[0] - 336678.0) < 0.01, f"center_dual cash 现值异常: {row}"
con.execute("UPDATE strategy_accounts_meta SET cash = cash + 6.4, updated_at=datetime('now','localtime') WHERE account_id='center_dual'")

# ── fusion_center +328（301055 9/10 除息 cash_div=0.1 factor=1.0 税率20%） ──
row = con.execute("SELECT cash FROM strategy_accounts_meta WHERE account_id='fusion_center'").fetchone()
assert row and abs(row[0] - 261598.0) < 0.01, f"fusion_center cash 现值异常: {row}"
con.execute("UPDATE strategy_accounts_meta SET cash = cash + 328.0, updated_at=datetime('now','localtime') WHERE account_id='fusion_center'")
pos = con.execute("SELECT shares, avg_cost, peak_price, stop_loss FROM strategy_positions WHERE account_id='fusion_center' AND code='301055'").fetchone()
assert pos and pos[0] == 4100 and abs(pos[1] - 27.92) < 0.01, f"301055 持仓现值异常: {pos}"
# 除权口径（与 adjust_corporate_action 同式）：total_cost - net_div 重摊；价格类 (v - cash_div)/factor
ac_new = round((27.92 * 4100 - 328.0) / 4100, 4)          # 27.84
peak_new = round((32.07 - 0.1) / 1.0, 2)                   # 31.97
sl_new = round((24.57 - 0.1) / 1.0, 2)                     # 24.47
con.execute("UPDATE strategy_positions SET avg_cost=?, peak_price=?, stop_loss=?, updated_at=datetime('now','localtime') "
            "WHERE account_id='fusion_center' AND code='301055'", (ac_new, peak_new, sl_new))
con.commit()

# ── JSON 同步（导出兼容层，与 DB 对齐） ──
for aid, add in [('center_dual', 6.4), ('fusion_center', 328.0)]:
    f = BASE / 'sim_accounts' / f'{aid}.json'
    d = json.load(open(f))
    d['cash'] = round(d['cash'] + add, 2)
    if aid == 'fusion_center':
        for p in d['positions']:
            if p['code'] == '301055':
                p['avg_cost'], p['peak_price'], p['stop_loss'] = ac_new, peak_new, sl_new
    tmp = f.with_suffix('.json.tmp')
    json.dump(d, open(tmp, 'w'), ensure_ascii=False, indent=2)
    tmp.rename(f)
    print(aid, 'JSON cash →', d['cash'])

# ── 回读验证 ──
for aid in ['center_dual', 'fusion_center']:
    db_cash = con.execute("SELECT cash FROM strategy_accounts_meta WHERE account_id=?", (aid,)).fetchone()[0]
    j_cash = json.load(open(BASE / 'sim_accounts' / f'{aid}.json'))['cash']
    print(f"{aid}: DB={db_cash} JSON={j_cash} 一致={abs(db_cash-j_cash)<0.01}")
print("301055 DB:", con.execute("SELECT shares,avg_cost,peak_price,stop_loss FROM strategy_positions WHERE account_id='fusion_center' AND code='301055'").fetchone())
con.close()
