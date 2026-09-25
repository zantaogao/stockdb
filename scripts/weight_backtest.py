#!/usr/bin/env python3
"""权重回测：不同 reg10/reg20/reg40 融合权重组合的历史 IC 对比（2026-08-03）。

方法（与 ic_daily.py 同口径）：
- 信号日 = signal_history 有全市场评分的交易日（7/23~7/31，7 天）
- 融合分 = w10*reg10 + w20*reg20 + w40*reg40（signal_history 原始模型分）
- 收益 = 次日 close / 信号日 close - 1（daily，YYYYMMDD）
- IC = Pearson(融合分, 次日收益)（逐日）
- 汇总：IC 均值 / std / IR / 方向胜率（IC>0 天数占比）/ 分组差（top10% 减 bottom10% 次日收益）
"""
import sqlite3
import duckdb
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.db import TUSHARE_DB_PATH

STATE_DB = Path(__file__).resolve().parent.parent / 'state.db'

# 权重组合： (名称, w10, w20, w40)
COMBOS = [
    ("baseline 25/50/25", 0.25, 0.50, 0.25),
    ("等权 33/33/33", 1/3, 1/3, 1/3),
    ("40d偏 25/40/35", 0.25, 0.40, 0.35),
    ("40d偏 25/25/50", 0.25, 0.25, 0.50),
    ("40d偏 20/30/50", 0.20, 0.30, 0.50),
    ("40d偏 20/40/40", 0.20, 0.40, 0.40),
    ("40d主导 10/30/60", 0.10, 0.30, 0.60),
    ("纯40d 0/0/100", 0.0, 0.0, 1.0),
    ("纯20d 0/100/0", 0.0, 1.0, 0.0),
]

state = sqlite3.connect(str(STATE_DB), timeout=30)
tushare = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)

# 1. 信号日（7/23 起，剔除 8/3——次日收益未出）
days = [r[0] for r in state.execute("""
    SELECT DISTINCT REPLACE(date,'-','') FROM signal_history
    WHERE reg10 IS NOT NULL AND reg20 IS NOT NULL AND reg40 IS NOT NULL
      AND REPLACE(date,'-','') >= '20260723' AND REPLACE(date,'-','') < '20260803'
    ORDER BY 1""").fetchall()]
print(f"信号日: {days}（{len(days)} 天）")

# 2. 每日数据：code -> (reg10, reg20, reg40)；收益用 daily
daily_ic = {name: [] for name, _, _, _ in COMBOS}   # name -> [每日IC]
daily_topdiff = {name: [] for name, _, _, _ in COMBOS}
day_detail = []

for d in days:
    rows = state.execute("""
        SELECT stock_code, reg10, reg20, reg40 FROM signal_history
        WHERE REPLACE(date,'-','')=? AND reg10 IS NOT NULL AND reg20 IS NOT NULL AND reg40 IS NOT NULL
    """, (d,)).fetchall()
    if not rows:
        continue
    codes = [r[0] for r in rows]
    ts_codes = [f"{c}.SH" if c.startswith(('6', '68', '9')) else f"{c}.SZ" for c in codes]
    # 次日
    nxt = tushare.execute("SELECT MIN(trade_date) FROM daily WHERE trade_date > ?", (d,)).fetchone()[0]
    if not nxt:
        continue
    ph = ','.join(['?'] * len(ts_codes))
    p1 = {r[0]: float(r[1]) for r in tushare.execute(
        f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", (d,) + tuple(ts_codes)).fetchall()}
    p2 = {r[0]: float(r[1]) for r in tushare.execute(
        f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", (nxt,) + tuple(ts_codes)).fetchall()}

    r10, r20, r40, rets = [], [], [], []
    for code, a, b, c in rows:
        ts = f"{code}.SH" if code.startswith(('6', '68', '9')) else f"{code}.SZ"
        if ts in p1 and ts in p2 and p1[ts] > 0:
            r10.append(float(a)); r20.append(float(b)); r40.append(float(c))
            rets.append((p2[ts] / p1[ts] - 1) * 100)
    if len(rets) < 30:
        continue
    arr10, arr20, arr40, arr_ret = map(np.array, (r10, r20, r40, rets))

    for name, w10, w20, w40 in COMBOS:
        fusion = w10 * arr10 + w20 * arr20 + w40 * arr40
        ic = float(np.corrcoef(fusion, arr_ret)[0, 1]) if np.std(fusion) > 0 else 0
        daily_ic[name].append(ic)
        # 分组差：top10% 与 bottom10% 次日收益均值差
        n10 = max(len(fusion) // 10, 1)
        order = np.argsort(fusion)
        top = arr_ret[order[-n10:]].mean()
        bot = arr_ret[order[:n10]].mean()
        daily_topdiff[name].append(top - bot)
    day_detail.append((d, nxt, len(rets)))

print("\n日期        次日     样本")
for d, n, s in day_detail:
    print(f"  {d}  -> {n}   {s}")

print("\n=== 权重组合对比（7 个信号日）===")
print(f"{'组合':<22}{'IC均值':<9}{'std':<8}{'IR':<8}{'胜率':<8}{'分组差均值'}")
results = []
for name, _, _, _ in COMBOS:
    ics = np.array(daily_ic[name])
    tds = np.array(daily_topdiff[name])
    m = ics.mean(); s = ics.std(ddof=1) if len(ics) > 1 else 0
    ir = m / s if s > 0 else 0
    win = sum(1 for x in ics if x > 0) / len(ics)
    results.append((name, m, ir, win, tds.mean()))
    print(f"{name:<22}{m:+.4f}   {s:.4f}  {ir:+.3f}  {win*100:4.0f}%  {tds.mean():+.3f}%")

# 排序：按 IR
print("\n按 IR 排序:")
for name, m, ir, win, td in sorted(results, key=lambda x: -x[2]):
    print(f"  {name:<22} IR={ir:+.3f}  IC均值={m:+.4f}  胜率={win*100:.0f}%  分组差={td:+.3f}%")

state.close(); tushare.close()
