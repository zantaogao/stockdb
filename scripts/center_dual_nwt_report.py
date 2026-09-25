#!/usr/bin/env python3
"""center_dual NW-t 复检报告（9月下旬攒够样本后自动跑）。
判点（09-06 商定）：
 1. 次日IC Newey-West t（lag=5）vs 朴素t —— 消除日频自相关虚高
 2. IC 分段：8月上旬牛市 / 8月中下旬-9月震荡，看方向是否只在牛市段成立
 3. fwd10_top10 成熟日均值；fwd20_top10 若已有值一并报
 4. 账户 center_dual 满20交易日后的分段超额（对比市场）
输出纯文本报告。"""
import sqlite3, numpy as np, os
BASE = os.path.expanduser('~/.hermes/stockdb')
st = sqlite3.connect(f'{BASE}/signals.db')
lg = sqlite3.connect(f'{BASE}/ledger.db')

rows = st.execute("SELECT date, ic FROM center_dual_ic_daily ORDER BY date").fetchall()
dates = [r[0] for r in rows]
ic = np.array([float(r[1]) for r in rows])
n = len(ic)
naive_t = ic.mean() / ic.std(ddof=1) * np.sqrt(n)
# Newey-West (lag=5) on mean of ic series
x = ic - ic.mean(); L = 5
g0 = (x * x).sum() / n
s = g0
for l in range(1, L + 1):
    w = 1 - l / (L + 1)
    gl = (x[l:] * x[:-l]).sum() / n
    s += 2 * w * gl
nw_t = ic.mean() / np.sqrt(s / n) if s > 0 else float('nan')

print(f'=== center_dual NW-t 复检  {np.datetime64("today")} ===')
print(f'次日IC: n={n}  均值={ic.mean():+.4f}  朴素t={naive_t:+.2f}  NW-t(lag5)={nw_t:+.2f}  胜率={np.mean(ic>0)*100:.0f}%')
# 分段: 牛市段<=20260814, 震荡段之后（两表日期格式不同，统一去掉横杠再比）
cut = '20260814'
for seg, m in [('牛市段(<=0814)', [d.replace('-', '') <= cut for d in dates]), ('震荡段(>0814)', [d.replace('-', '') > cut for d in dates])]:
    sub = ic[np.array(m)]
    if len(sub) >= 3:
        tt = sub.mean() / sub.std(ddof=1) * np.sqrt(len(sub)) if sub.std(ddof=1) > 0 else float('nan')
        print(f'  {seg}: n={len(sub)}  均值={sub.mean():+.4f}  朴素t={tt:+.2f}  胜率={np.mean(sub>0)*100:.0f}%')

f10 = st.execute("SELECT date, fwd10_top10 FROM center_dual_ic_daily WHERE fwd10_top10 IS NOT NULL ORDER BY date").fetchall()
f20 = st.execute("SELECT date, fwd20_top10 FROM center_dual_ic_daily WHERE fwd20_top10 IS NOT NULL ORDER BY date").fetchall()
if f10:
    v = np.array([float(r[1]) for r in f10])
    print(f'fwd10_top10: n={len(v)}  均值={v.mean():+.2f}%/票·10d  中位={np.median(v):+.2f}%  正日={np.mean(v>0)*100:.0f}%')
if f20:
    v = np.array([float(r[1]) for r in f20])
    print(f'fwd20_top10: n={len(v)}  均值={v.mean():+.2f}%/票·20d')
else:
    print('fwd20_top10: 尚无成熟样本')

acc = lg.execute("""SELECT date, daily_ret, market_ret FROM strategy_accounts
                   WHERE account_id='center_dual' ORDER BY date""").fetchall()
if acc:
    d = [a[0] for a in acc]
    ret = np.array([float(a[1]) / 100 for a in acc])
    mkt = np.array([float(a[2]) / 100 for a in acc])
    cum_r = (np.prod(1 + ret) - 1) * 100
    cum_m = (np.prod(1 + mkt) - 1) * 100
    print(f'账户: {d[0]}~{d[-1]} 共{len(d)}日  累计{cum_r:+.2f}%  市场{cum_m:+.2f}%  超额{cum_r-cum_m:+.2f}pp')
    if len(d) >= 20:
        ex = ret - mkt
        t = ex.mean() / ex.std(ddof=1) * np.sqrt(len(ex))
        print(f'  日超额t值={t:+.2f}（>=2 才算统计显著）')
    else:
        print(f'  （不足20交易日，超额无统计意义）')
print('判点参考: NW-t>=2 且 震荡段IC为正 → 可考虑升格为二号主力候选; 否则继续观察.')