#!/usr/bin/env python3
"""系统统计: 持仓盈亏/信号/IC 的期望·方差·分布 (2026-08-27)
用统计视角看系统: 期望值(均值) + 波动(标准差) + 分布形态。
"""
import sqlite3, duckdb
import numpy as np
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb')
s = sqlite3.connect(str(BASE / 'state.db'))

def stats(a, name, unit=''):
    a = np.array([x for x in a if x is not None and not (isinstance(x, float) and np.isnan(x))], dtype=float)
    if len(a) == 0:
        print(f"{name}: 无数据")
        return
    mean, std = a.mean(), a.std(ddof=1) if len(a) > 1 else 0
    print(f"{name}: n={len(a)} 期望={mean:.3f}{unit} 标准差={std:.3f}{unit} "
          f"min={a.min():.3f} p25={np.percentile(a,25):.3f} 中位={np.median(a):.3f} "
          f"p75={np.percentile(a,75):.3f} max={a.max():.3f}")

print("=" * 60)
print("1) 持仓统计 (期望值/方差视角)")
print("=" * 60)
rows = s.execute("SELECT code, name, shares, avg_cost, latest_price, pnl, pnl_pct FROM holdings WHERE status='持仓'").fetchall()
if not rows:
    rows = s.execute("SELECT code, name, shares, avg_cost, latest_price, pnl, pnl_pct FROM holdings").fetchall()
print(f"持仓 {len(rows)} 只")
pnls = []
costs = []
for code, name, shares, cost, price, pnl, pnl_pct in rows:
    cost = float(cost); price = float(price); shares = float(shares)
    p = (price / cost - 1) * 100 if cost > 0 else 0
    pnls.append(p)
    costs.append(cost * shares)
stats(pnls, "  单只盈亏% (期望=平均盈亏)", unit='%')
tot_cost = sum(costs)
print(f"  持仓总成本: {tot_cost/10000:.1f}万  可用现金: 153311.3 ({(153311.3/(tot_cost+153311.3))*100:.1f}%)")
win = sum(1 for p in pnls if p > 0)
print(f"  盈利 {win}/{len(pnls)} ({win/len(pnls)*100:.0f}%)  亏损 {len(pnls)-win}  盈亏比(均值盈利/|均值亏损|): "
      f"{np.mean([p for p in pnls if p>0]):.2f}/{abs(np.mean([p for p in pnls if p<=0])):.2f}" if any(p>0 for p in pnls) and any(p<=0 for p in pnls) else "  单边")

print()
print("=" * 60)
print("2) fusion_3f 信号分布 (最新日)")
print("=" * 60)
d = s.execute("SELECT MAX(date) FROM fusion_3f_signals").fetchone()[0]
print(f"  最新日: {d}")
sc = s.execute("SELECT fusion_3f_score FROM fusion_3f_signals WHERE date=?", [d]).fetchall()
stats([r[0] for r in sc], "  fusion_3f_score 全市场")
sg = s.execute("SELECT COUNT(*) FROM fusion_3f_signals WHERE date=? AND signal='强买'", [d]).fetchone()[0]
sg2 = s.execute("SELECT COUNT(*) FROM fusion_3f_signals WHERE date=? AND signal='强卖'", [d]).fetchone()[0]
print(f"  强买 {sg} / 强卖 {sg2} (占比 {sg/(sg+sg2)*100:.1f}% / {sg2/(sg+sg2)*100:.1f}%)")

print()
print("=" * 60)
print("3) 模型 IC 统计 (ic_daily 最近20个信号日)")
print("=" * 60)
ic = s.execute("SELECT signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40 FROM ic_daily ORDER BY signal_date DESC LIMIT 20").fetchall()
ic = ic[::-1]
for i, nm in [(1, 'ic_fusion'), (2, 'ic_reg10'), (3, 'ic_reg20'), (4, 'ic_reg40')]:
    stats([r[i] for r in ic if r[i] is not None], f"  {nm} 期望(20日)", unit='')

print()
print("=" * 60)
print("4) 因子滚动 IC (factor_ic_roll 最新, 含期望/方差/ICIR)")
print("=" * 60)
fr = s.execute("SELECT factor_name, mean_ic, std_ic, icir, win_rate, n_days, max_ic, min_ic FROM factor_ic_roll ORDER BY as_of_date DESC LIMIT 20").fetchall()
for r in fr:
    if r[0] in ('fusion_3f_score', '强买'):
        print(f"  {r[0]}: mean_ic={r[1]} std_ic={r[2]} icir={r[3]} win={r[4]} n={r[5]}")

print()
print("=" * 60)
print("5) Cron 健康 (30天)")
print("=" * 60)
# 从 cron 状态推断: 简报已显示 5 个 error
print("  简报显示 5 个任务上次未成功: IC监控/ETF评分/CMMR IC/ETF净值/NAS备份")

s.close()
