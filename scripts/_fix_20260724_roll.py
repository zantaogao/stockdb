"""重算 20260724 强买信号统计（用修正后的 top15% 标签）并更新 factor_ic_roll"""
import sqlite3, numpy as np
from pathlib import Path
from scipy.stats import spearmanr

BASE = Path.home() / '.hermes' / 'stockdb'
STATE_DB = BASE / 'state.db'
SD = '20260724'

state = sqlite3.connect(str(STATE_DB), timeout=30)

def code_to_ts(c):
    c = str(c)
    return f"{c}.SH" if c.startswith(('6', '68', '9')) else f"{c}.SZ"

# 1) 修正后的强买集合
sb = [r[0] for r in state.execute(
    "SELECT stock_code FROM fusion_3f_signals WHERE REPLACE(date,'-','')=? AND signal='强买'", (SD,)
).fetchall()]
print(f"修正后强买: {len(sb)} 只")

# 2) 全集合 scores + returns（同日，用于强买 IC）
rows = state.execute(
    "SELECT stock_code, fusion_3f_score FROM fusion_3f_signals WHERE REPLACE(date,'-','')=? AND fusion_3f_score>0", (SD,)
).fetchall()

# 查价格（用 tushare.db 的 daily）
import duckdb
tushare = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
ND = tushare.execute("SELECT MIN(trade_date) FROM daily WHERE trade_date > ?", (SD,)).fetchone()[0]
print(f"次日: {ND}")

codes = [code_to_ts(c) for c, s in rows]
ph = ','.join(['?'] * len(codes))
p0 = {r[0]: float(r[1]) for r in tushare.execute(f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", (SD,) + tuple(codes)).fetchall()}
p1 = {r[0]: float(r[1]) for r in tushare.execute(f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", (ND,) + tuple(codes)).fetchall()}
tushare.close()

scores, returns, paired_codes = [], [], []
for code, score in rows:
    ts = code_to_ts(code)
    if ts in p0 and ts in p1 and p0[ts] > 0:
        scores.append(float(score)); returns.append((p1[ts] / p0[ts] - 1) * 100); paired_codes.append(code)

print(f"配对: {len(scores)}")

# 3) 强买子集统计
sb_ret = [returns[i] for i in range(len(paired_codes)) if paired_codes[i] in set(sb)]
sb_scores = [scores[i] for i in range(len(paired_codes)) if paired_codes[i] in set(sb)]
ic, _ = spearmanr(sb_scores, sb_ret)
win = sum(1 for r in sb_ret if r > 0) / len(sb_ret)
print(f"强买: n={len(sb_ret)} IC={ic:.4f} 胜率={win*100:.1f}% mean={np.mean(sb_ret):+.2f}% median={np.median(sb_ret):+.2f}%")

# 4) 更新 factor_ic_roll
state.execute("""
    INSERT OR REPLACE INTO factor_ic_roll
    (factor_name, as_of_date, window, mean_ic, std_ic, icir, win_rate,
     max_ic, min_ic, n_days, ret_horizon, group_name, mean_ret, median_ret)
    VALUES (?, ?, 20, ?, 0, 0, ?, NULL, NULL, ?, 1, '三因子融合', ?, ?)
""", ('fusion_3f_强买', SD, round(ic, 4), round(win, 4), len(sb_ret), round(float(np.mean(sb_ret)), 2), round(float(np.median(sb_ret)), 2)))
state.commit()
state.close()
print("factor_ic_roll 已更新 (fusion_3f_强买, as_of=20260724)")
