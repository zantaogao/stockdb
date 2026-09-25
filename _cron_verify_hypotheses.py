#!/usr/bin/env python3
"""分钟线假设验证：开盘强弱/波动率/振幅量能组合 2026-08-08
数据: tdx_intraday_feat (997293行/116天) + daily 次日收益
方法: 分组均值/中位 + t 检验 (scipy)
"""
import sqlite3, duckdb
import numpy as np
import pandas as pd
from scipy import stats

STATE = '/Users/zantao/.hermes/stockdb/state.db'
TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'
s = sqlite3.connect(STATE)
t = duckdb.connect(TUSHARE, read_only=True)

print("加载数据...")
# 特征 + 次日收益（内存 join）
feat = pd.read_sql("SELECT date, code, open30_ret, tail30_ret, vwap_dev, rv_1m, amp_intra, vol_dist_am FROM tdx_intraday_feat", s)
tds = [str(r[0]) for r in t.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date >= '20260224' ORDER BY trade_date").fetchall()]
nx = {d: tds[i+1] for i, d in enumerate(tds[:-1])}
def c2t(c): return f"{c}.SH" if str(c).startswith(("6","68","9")) else f"{c}.SZ"
px = {}
for d, tc, cl in t.execute("SELECT trade_date, ts_code, close FROM daily WHERE trade_date >= '20260224'").fetchall():
    px.setdefault(str(d), {})[tc] = float(cl)

ret_rows = []
for _, r in feat.iterrows():
    dd, nxt = str(r['date']), nx.get(str(r['date']))
    if not nxt: continue
    tc = c2t(r['code'])
    c0, c1 = px.get(dd, {}).get(tc), px.get(nxt, {}).get(tc)
    if not c0 or not c1 or c0 <= 0: continue
    ret_rows.append((r['date'], r['code'], (c1/c0-1)*100, r['open30_ret'], r['tail30_ret'], r['rv_1m'], r['amp_intra'], r['vol_dist_am']))
df = pd.DataFrame(ret_rows, columns=['date','code','ret','open30','tail30','rv1m','amp','voldist'])
print(f"样本: {len(df)} 行")

def report(name, mask, baseline):
    g = df[mask]['ret']
    if len(g) < 100:
        print(f"{name}: 样本不足({len(g)})"); return
    tstat, p = stats.ttest_1samp(g, baseline)
    print(f"{name}: n={len(g):>7} 次日均值 {g.mean():>+6.2f}% 中位 {g.median():>+6.2f}% "
          f"vs基准 {baseline:+.2f}%  t={tstat:+.1f} p={p:.2e}")

base = df['ret'].mean()
print(f"\n全样本基准: 次日均值 {base:+.3f}%")

# ═══ 假设1: 开盘强弱 ═══
print("\n── 假设1a: open30_ret 大 → 次日继续强势? ──")
q10, q90 = df['open30'].quantile(0.10), df['open30'].quantile(0.90)
report("开盘强(top10% open30)", df['open30'] > q90, base)
report("开盘弱(bottom10% open30)", df['open30'] < q10, base)
print("── 假设1b: 尾盘跌+开盘强 = 主力低吸? ──")
mask_low = (df['tail30'] < -0.005) & (df['open30'] > q50 if (q50:=df['open30'].median()) else False)
report("尾盘跌+开盘强", (df['tail30'] < -0.005) & (df['open30'] > df['open30'].median()), base)
report("尾盘跌+开盘弱", (df['tail30'] < -0.005) & (df['open30'] < df['open30'].median()), base)
report("尾盘涨+开盘强", (df['tail30'] > 0.005) & (df['open30'] > df['open30'].median()), base)

# ═══ 假设2: 波动率 ═══
print("\n── 假设2: rv_1m 低 → 方向更明确 / 高 → 震荡 ──")
qlow, qhigh = df['rv1m'].quantile(0.25), df['rv1m'].quantile(0.75)
lo, hi = df[df['rv1m'] <= qlow], df[df['rv1m'] >= qhigh]
print(f"低波动(<=P25): 次日|收益|均值 {lo['ret'].abs().mean():.3f}%  次日收益std {lo['ret'].std():.3f}%  (n={len(lo)})")
print(f"高波动(>=P75): 次日|收益|均值 {hi['ret'].abs().mean():.3f}%  次日收益std {hi['ret'].std():.3f}%  (n={len(hi)})")
report("低波动次日收益", df['rv1m'] <= qlow, base)
report("高波动次日收益", df['rv1m'] >= qhigh, base)

# ═══ 假设3: 振幅+量能 ═══
print("\n── 假设3: 振幅大+量能集中=主力? 均匀=散户? ──")
amp_hi = df['amp'] > df['amp'].quantile(0.75)
vd_hi = df['voldist'] > df['voldist'].quantile(0.75)
vd_lo = df['voldist'] < df['voldist'].quantile(0.25)
report("振幅大+量集中(早盘放量)", amp_hi & vd_hi, base)
report("振幅大+量均匀", amp_hi & vd_lo, base)
report("振幅小+量集中", (~amp_hi) & vd_hi, base)
report("振幅小+量均匀", (~amp_hi) & vd_lo, base)
s.close(); t.close()
