#!/usr/bin/env python3
"""独立复算验证：短期动量因子 7/27 的 IC（无未来泄漏口径 vs 泄漏口径）"""
import duckdb
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.db import TUSHARE_DB_PATH

tushare = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)

# 全 A 股（与 factor_ic.py 同口径过滤）
raw = [r[0] for r in tushare.execute("""
    SELECT symbol FROM stock_basic
    WHERE market != '北交所' AND symbol NOT LIKE '8%' AND symbol NOT LIKE '4%'
    AND (name NOT LIKE '%ST%' OR name IS NULL)
""").fetchall()]
codes = []
for s in raw:
    tscode = f"{s}.SH" if s.startswith(('6', '68', '9')) else f"{s}.SZ"
    codes.append(tscode)
ph = ','.join(['?'] * len(codes))

SIGNAL = '20260727'   # 信号日
NEXT = '20260728'     # 次日（收益日）

# 收益：7/27 收盘 -> 7/28 收盘
p1 = {r[0]: float(r[1]) for r in tushare.execute(
    f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", (SIGNAL,) + tuple(codes)).fetchall()}
p2 = {r[0]: float(r[1]) for r in tushare.execute(
    f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", (NEXT,) + tuple(codes)).fetchall()}

# 无泄漏口径：动量只用 <= 7/27 的价格
# 泄漏口径（旧 bug）：动量用 <= 8/3（daily 最新）的价格，closes[-1]=8/3
# 手动构造：取每只股票 7/27 及之前 10 天 + 对比 8/3 最新
scores_clean, rets = [], []
scores_leaky, = [],  # 泄漏版稍后从库里对比

for ts in codes:
    if ts not in p1 or ts not in p2 or p1[ts] <= 0:
        continue
    ret = (p2[ts] / p1[ts] - 1) * 100
    # 截至 7/27 的收盘序列（10 个交易日）
    rows = tushare.execute(
        "SELECT trade_date, close FROM daily WHERE ts_code=? AND trade_date <= ? ORDER BY trade_date DESC LIMIT 10",
        (ts, SIGNAL)).fetchall()
    if len(rows) < 10:
        continue
    closes = [float(r[1]) for r in rows][::-1]   # 升序，closes[-1] = 7/27
    chg5 = (closes[-1] / closes[-5] - 1) * 100
    chg10 = (closes[-1] / closes[0] - 1) * 100
    scores_clean.append((chg5 + chg10) / 2)
    rets.append(ret)

scores_clean = np.array(scores_clean)
rets = np.array(rets)
ic_clean = float(np.corrcoef(scores_clean, rets)[0, 1])
print(f"无泄漏口径 短期动量 7/27: IC={ic_clean:.4f}  n={len(scores_clean)}")
print(f"库中泄漏值（旧代码算出）:   IC=0.6061  n=4985")
print(f"差异: {abs(ic_clean - 0.6061):.4f} → {'⚠️ 泄漏确实存在，修复有效' if abs(ic_clean - 0.6061) > 0.01 else '无显著差异'}")

# 泄漏版验证：用 closes[-1]=8/3（最新）算的动量
scores_leaky, rets_leaky = [], []
for ts in codes:
    if ts not in p1 or ts not in p2 or p1[ts] <= 0:
        continue
    rows = tushare.execute(
        "SELECT trade_date, close FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 10",
        (ts,)).fetchall()  # 无截止 = 旧 bug
    if len(rows) < 10:
        continue
    closes = [float(r[1]) for r in rows][::-1]
    chg5 = (closes[-1] / closes[-5] - 1) * 100
    chg10 = (closes[-1] / closes[0] - 1) * 100
    scores_leaky.append((chg5 + chg10) / 2)
    rets_leaky.append((p2[ts] / p1[ts] - 1) * 100)
scores_leaky = np.array(scores_leaky)
rets_leaky = np.array(rets_leaky)
ic_leaky = float(np.corrcoef(scores_leaky, rets_leaky)[0, 1])
print(f"泄漏口径（旧 bug 复刻）:      IC={ic_leaky:.4f}  n={len(scores_leaky)} → 应接近库中 0.6061")
tushare.close()
