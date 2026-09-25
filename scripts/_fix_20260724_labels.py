"""一次性修复：fusion_3f_signals 20260724 历史标签（旧引擎写入，非百分位分级）。
按新引擎逻辑（当日融合分百分位：强买 top15% / 强卖 bottom15%）重算 signal 列，不动分数。
先备份受影响行到 CSV，再 UPDATE，最后验证分布。"""
import sqlite3, csv, numpy as np
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
STATE_DB = BASE / 'state.db'
TARGET = '20260724'

state = sqlite3.connect(str(STATE_DB), timeout=30)

# 0) 备份
rows = state.execute(
    "SELECT stock_code, date, reg10, ma_decay, flow_alpha, vol_adj, fusion_3f_score, signal "
    "FROM fusion_3f_signals WHERE REPLACE(date,'-','') = ?", (TARGET,)
).fetchall()
bak_path = BASE / 'db_backups' / f'fusion_3f_signals_{TARGET}_before_relabel.csv'
bak_path.parent.mkdir(exist_ok=True)
with open(bak_path, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['stock_code', 'date', 'reg10', 'ma_decay', 'flow_alpha', 'vol_adj', 'fusion_3f_score', 'signal'])
    w.writerows(rows)
print(f"备份 {len(rows)} 行 → {bak_path}")

# 1) 按引擎逻辑算阈值
scores = sorted(r[6] for r in rows if r[6] is not None)
n = len(scores)
buy_threshold = scores[int(n * 0.85)]
hold_top = scores[int(n * 0.60)]
hold_bot = scores[int(n * 0.40)]
sell_threshold = scores[int(n * 0.15)]
print(f"n={n} 阈值: 强买>={buy_threshold:.2f} 买>={hold_top:.2f} 持>={hold_bot:.2f} 卖>={sell_threshold:.2f} 强卖<{sell_threshold:.2f}")

def assign(score):
    if score >= buy_threshold: return '强买'
    if score >= hold_top: return '买'
    if score >= hold_bot: return '持'
    if score >= sell_threshold: return '卖'
    return '强卖'

# 2) UPDATE
counts = {}
for code, date, *_rest, score, old_sig in rows:
    new_sig = assign(score)
    state.execute(
        "UPDATE fusion_3f_signals SET signal=? WHERE stock_code=? AND REPLACE(date,'-','')=?",
        (new_sig, code, TARGET)
    )
    counts[new_sig] = counts.get(new_sig, 0) + 1
state.commit()

# 3) 验证分布
print("\n=== 重打标签后分布 ===")
for sig in ['强买', '买', '持', '卖', '强卖']:
    c = counts.get(sig, 0)
    print(f"  {sig}: {c} ({c/n*100:.1f}%)")

state.close()
