#!/usr/bin/env python3
"""三模型重训节奏分析：可信IC稳定性 + ic_window积累 + 训练成本"""
import sqlite3
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
c = sqlite3.connect(str(BASE / 'state.db'))

print('=== 1. 可信模型 IC（8/3 起，8/1 前评分管线失真作废）===')
rows = c.execute("""
    SELECT signal_date, ic_reg10, ic_reg20, ic_reg40, ic_fusion FROM ic_daily
    WHERE signal_date >= '20260803' ORDER BY signal_date
""").fetchall()
if rows:
    import numpy as np
    print(f"{'signal_date':<12}{'reg10':>8}{'reg20':>8}{'reg40':>8}{'fusion':>8}")
    for r in rows:
        print(f"{str(r[0]):<12}{r[1]:>8.3f}{r[2]:>8.3f}{r[3]:>8.3f}{r[4]:>8.3f}")
    # 各模型统计
    for i, name in [(1,'reg10'), (2,'reg20'), (3,'reg40'), (4,'fusion')]:
        vals = [r[i] for r in rows if r[i] is not None]
        if len(vals) >= 2:
            mean = np.mean(vals)
            std = np.std(vals, ddof=1)
            ir = mean / std if std > 0 else 0
            win = sum(1 for v in vals if v > 0) / len(vals)
            print(f"  {name}: 均值={mean:+.3f} std={std:.3f} IR={ir:+.2f} 胜率={win:.0%} (n={len(vals)})")

print()
print('=== 2. ic_window 真窗口 IC 积累进度（模型预测窗口匹配的验证）===')
wrows = c.execute("""
    SELECT signal_date, ic_reg10_w10, ic_reg20_w20, ic_reg40_w40, ic_fusion_w20
    FROM ic_window ORDER BY signal_date
""").fetchall()
if wrows:
    for r in wrows:
        print(f"  signal_date={r[0]}  reg10_w10={r[1]}  reg20_w20={r[2]}  reg40_w40={r[3]}  fusion_w20={r[4]}")
else:
    print("  (无数据)")

print()
print('=== 3. 信号日 vs 今日（40d 窗口需要 8 周积累到哪了）===')
td = c.execute("SELECT MAX(REPLACE(date,'-','')) FROM signal_history").fetchone()[0]
print(f"  最新信号日: {td} | 今天: 20260807")
print("  40d 窗口 IC 需 40 个交易日后才回填（最早 ~8/19 有第一个）")

c.close()
