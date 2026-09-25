#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IC 聚合 (signals.db 只读)"""
import os, sqlite3
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('signals.db')

print('=== signals.db 全部表 ===')
for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
    print(' ', r[0])

def stat(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    n = len(vals)
    m = sum(vals) / n
    pos = sum(1 for v in vals if v > 0)
    return n, m, pos, vals

print()
print('=== ic_daily 近10信号日 (fwd1 口径) ===')
rows = c.execute("SELECT signal_date, ic_reg10, ic_reg20, ic_reg40, ic_fusion FROM ic_daily ORDER BY signal_date DESC LIMIT 10").fetchall()
print('signal_date       reg10    reg20    reg40    fusion')
for r in rows:
    f = lambda x: f"{x:+.4f}" if x is not None else "   n/a"
    print(f"{r[0]}  {f(r[1])} {f(r[2])} {f(r[3])} {f(r[4])}")
for idx, nm in [(1, 'reg10'), (2, 'reg20'), (3, 'reg40'), (4, 'fusion')]:
    s = stat([r[idx] for r in rows])
    if s:
        print(f"  {nm}: n={s[0]} mean={s[1]:+.4f} 正{s[2]}/{s[0]}")
    s5 = stat([r[idx] for r in rows[:5]])
    if s5:
        print(f"    近5日 mean={s5[1]:+.4f} 正{s5[2]}/5")

print()
print('=== ic_daily 近10 → 近5 vs 近6-10 对比 ===')
if len(rows) >= 10:
    for idx, nm in [(1, 'reg10'), (2, 'reg20'), (3, 'reg40'), (4, 'fusion')]:
        a = stat([r[idx] for r in rows[:5]])
        b = stat([r[idx] for r in rows[5:10]])
        if a and b:
            print(f"  {nm}: 近5={a[1]:+.4f}(正{a[2]})  前5={b[1]:+.4f}(正{b[2]})  变化={a[1]-b[1]:+.4f}")

print()
print('=== ic_window 近12信号日 w10 口径 ===')
rows = c.execute("""SELECT signal_date, ic_reg10_w10, ic_fusion_w10, ic_center_w10, ic_dual_w10,
                           fwd10_top_center, fwd10_top_main, fwd10_top
                    FROM ic_window ORDER BY signal_date DESC LIMIT 12""").fetchall()
print('signal_date  reg10_w10 fusion_w10 center_w10 dual_w10 | top10center top10main top10fusion')
for r in rows:
    f = lambda x: f"{x:+.4f}" if x is not None else "   n/a"
    g = lambda x: f"{x:+.2f}" if x is not None else "  n/a"
    print(f"{r[0]}  {f(r[1])} {f(r[2])} {f(r[3])} {f(r[4])} | {g(r[5])} {g(r[6])} {g(r[7])}")
labels = ['reg10_w10', 'fusion_w10', 'center_w10', 'dual_w10']
for i, nm in enumerate(labels):
    s = stat([r[i + 1] for r in rows])
    if s:
        print(f"  {nm}: n={s[0]} mean={s[1]:+.4f} 正{s[2]}/{s[0]}")
    s5 = stat([r[i + 1] for r in rows[:5]])
    if s5:
        print(f"    近5 mean={s5[1]:+.4f} 正{s5[2]}/5")

print()
print('=== ic_window w20/w40 可用行(成熟) ===')
rows = c.execute("""SELECT signal_date, ic_reg10_w10, ic_reg20_w20, ic_reg40_w40, ic_fusion_w20, ic_fusion_w40
                    FROM ic_window WHERE ic_reg20_w20 IS NOT NULL OR ic_reg40_w40 IS NOT NULL
                    ORDER BY signal_date DESC LIMIT 10""").fetchall()
for r in rows:
    f = lambda x: f"{x:+.4f}" if x is not None else "   n/a"
    print(f"{r[0]}  reg10_w10={f(r[1])} reg20_w20={f(r[2])} reg40_w40={f(r[3])} fus_w20={f(r[4])} fus_w40={f(r[5])}")

print()
print('=== center_dual_ic_daily 近12信号日 ===')
rows = c.execute("""SELECT date, ic, top_ret, bottom_ret, fwd10_top10 FROM center_dual_ic_daily
                    ORDER BY date DESC LIMIT 12""").fetchall()
for r in rows:
    f = lambda x: f"{x:+.4f}" if x is not None else "   n/a"
    print(f"{r[0]}  ic={f(r[1])}  top={r[2]}  bottom={r[3]}  fwd10_top10={r[4]}")
s = stat([r[1] for r in rows])
if s:
    print(f"  近12: n={s[0]} mean={s[1]:+.4f} 正{s[2]}/{s[0]}")
s = stat([r[1] for r in rows[:5]])
if s:
    print(f"  近5: mean={s[1]:+.4f} 正{s[2]}/5")

print()
print('=== fusion_ic_daily 按 forward_days 均值 (近12行) ===')
rows = c.execute("SELECT date, ic, forward_days, win_rate FROM fusion_ic_daily ORDER BY date DESC LIMIT 12").fetchall()
for r in rows:
    print(f"{r[0]}  fwd{r[2]}  ic={r[1]:+.4f}  win_rate={r[3]}")
s = stat([r[1] for r in rows])
if s:
    print(f"  近12: n={s[0]} mean={s[1]:+.4f} 正{s[2]}/{s[0]}")
s = stat([r[1] for r in rows[:5]])
if s:
    print(f"  近5: mean={s[1]:+.4f} 正{s[2]}/5")
c.close()
