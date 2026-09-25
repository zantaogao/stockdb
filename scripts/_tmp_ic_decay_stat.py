#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三模型信号衰减趋势统计（一次性分析脚本）
口径：ic_daily=次日哨兵IC(Pearson, 8/3起可信)；ic_window=真窗口IC(Spearman)
"""
import sqlite3, math, statistics
from scipy import stats
stats.mean = statistics.mean
stats.median = statistics.median

DB = '/tmp/sig_stat.db'  # 快照副本：原库被面板/写入进程持有，只读副本避免抢锁
conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)

def slope_test(dates, vals):
    """OLS斜率 + t检验。dates转成序号。返回 (斜率/日, p值, n)"""
    n = len(vals)
    if n < 4:
        return None
    x = list(range(n))
    res = stats.linregress(x, vals)
    return res.slope, res.pvalue, n

def fmt(v, w=7, d=4):
    return ' None ' if v is None else f'{v:>{w}.{d}f}'

print('=' * 78)
print('A. 日历时间维度的IC趋势（哨兵IC，次日收益验证，8/3起）')
print('=' * 78)
rows = conn.execute("""
    SELECT signal_date, ic_reg10, ic_reg20, ic_reg40, ic_fusion
    FROM ic_daily WHERE REPLACE(CAST(signal_date AS CHAR),'-','') >= '20260803'
    ORDER BY signal_date
""").fetchall()
print(f'信号日: {rows[0][0]} ~ {rows[-1][0]}，共 {len(rows)} 天')
print()
print(f"{'列':<12}{'全期均值':>9}{'前半均值':>9}{'后半均值':>9}{'斜率/日':>10}{'p值':>8}{'正IC占比':>8}")
cols = ['ic_reg10', 'ic_reg20', 'ic_reg40', 'ic_fusion']
names = {'ic_reg10': 'reg10(10d)', 'ic_reg20': 'reg20(20d)', 'ic_reg40': 'reg40(40d)', 'ic_fusion': '三模型融合'}
for i, c in enumerate(cols, start=1):
    vals = [r[i] for r in rows if r[i] is not None]
    if len(vals) < 4:
        continue
    h = len(vals) // 2
    first, second = sum(vals[:h])/h, sum(vals[h:])/(len(vals)-h)
    sl, p, n = slope_test(None, vals)
    pos = sum(1 for v in vals if v > 0) / len(vals)
    print(f"{names[c]:<12}{stats.mean(vals):>9.4f}{first:>10.4f}{second:>10.4f}{sl:>10.5f}{p:>8.3f}{pos:>7.0%}")

# 按周细分，看逐段
print()
print('逐周均值（观察是否逐周走低）:')
weeks = {}
for r in rows:
    d = str(r[0]).replace('-', '')
    # 周编号: 8/3是周一
    wk = (int(d) - 20260803)
    from datetime import date
    dt = date(int(d[:4]), int(d[4:6]), int(d[6:]))
    key = dt.isocalendar()[1]
    weeks.setdefault(key, []).append(r)
print(f"{'周':<6}{'天数':>4} " + ''.join(f'{names[c]:>12}' for c in cols))
for key in sorted(weeks):
    wr = weeks[key]
    line = f"W{key:<5}{len(wr):>4} "
    for i, c in enumerate(cols, start=1):
        vals = [r[i] for r in wr if r[i] is not None]
        line += f"{stats.mean(vals):>12.4f}" if vals else f"{'-':>12}"
    print(line)

print()
print('=' * 78)
print('B. 真窗口IC趋势（ic_window，Spearman，衰减判断的正尺子）')
print('=' * 78)
wcols = ['ic_reg10_w10', 'ic_reg20_w20', 'ic_reg40_w40', 'ic_fusion_w10', 'ic_fusion_w20', 'ic_fusion_w40']
wnames = {'ic_reg10_w10': 'reg10×w10', 'ic_reg20_w20': 'reg20×w20', 'ic_reg40_w40': 'reg40×w40',
          'ic_fusion_w10': '融合×w10', 'ic_fusion_w20': '融合×w20(主)', 'ic_fusion_w40': '融合×w40'}
avail = [c for c in wcols if c in [r[1] for r in conn.execute("PRAGMA table_info(ic_window)")]]
hdr = conn.execute("SELECT " + ','.join(avail) + " FROM ic_window ORDER BY signal_date").description
wrows = conn.execute("SELECT signal_date," + ','.join(avail) + " FROM ic_window ORDER BY signal_date").fetchall()
wrows = [r for r in wrows if str(r[0]).replace('-', '') >= '20260803']
print(f'信号日: {wrows[0][0]} ~ {wrows[-1][0]}，共 {len(wrows)} 行')
print()
print(f"{'列':<14}{'n':>3}{'均值':>9}{'前段':>9}{'后段':>9}{'斜率/日':>10}{'p值':>8}")
for j, c in enumerate(avail, start=1):
    vals = [r[j] for r in wrows if r[j] is not None]
    if len(vals) < 2:
        print(f"{wnames[c]:<14}{len(vals):>3}{stats.mean(vals) if vals else float('nan'):>9.4f}   (样本不足，积累中)")
        continue
    h = max(1, len(vals)//2)
    first, second = sum(vals[:h])/h, sum(vals[h:])/(len(vals)-h)
    if len(vals) >= 4:
        sl, p, _ = slope_test(None, vals)
        print(f"{wnames[c]:<14}{len(vals):>3}{stats.mean(vals):>9.4f}{first:>10.4f}{second:>10.4f}{sl:>10.5f}{p:>8.3f}")
    else:
        print(f"{wnames[c]:<14}{len(vals):>3}{stats.mean(vals):>9.4f}{first:>10.4f}{second:>10.4f}   (n<4不拟合)")

print()
print('逐日明细（真窗口IC）:')
print(f"{'信号日':<12}" + ''.join(f'{wnames[c]:>13}' for c in avail))
for r in wrows:
    line = f"{str(r[0]):<12}"
    for j in range(1, len(avail)+1):
        line += f"{r[j]:>13.4f}" if r[j] is not None else f"{'-':>13}"
    print(line)

print()
print('=' * 78)
print('C. 融合分信号的期限衰减（同一分数对不同持有期的预测力）')
print('=' * 78)
for c, lbl in [('ic_fusion_w10', '10日持有'), ('ic_fusion_w20', '20日持有(主窗口)'), ('ic_fusion_w40', '40日持有')]:
    if c not in avail:
        continue
    idx = avail.index(c) + 1
    vals = [r[idx] for r in wrows if r[idx] is not None]
    if vals:
        print(f"{lbl:<16} n={len(vals):>3}  均值IC={stats.mean(vals):.4f}  中位={stats.median(vals):.4f}  正占比={sum(1 for v in vals if v>0)/len(vals):.0%}")
conn.close()