#!/usr/bin/env python3
"""验证用户 7 点观察: VWAP偏离/振幅×波动/量价/4象限/VWAP×振幅/极端值/量能4档 2026-08-08"""
import sqlite3, duckdb
import numpy as np
import pandas as pd
from scipy import stats

STATE = '/Users/zantao/.hermes/stockdb/state.db'
TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'
s = sqlite3.connect(STATE)
t = duckdb.connect(TUSHARE, read_only=True)

feat = pd.read_sql("SELECT date, code, open30_ret, tail30_ret, vwap_dev, rv_1m, amp_intra, vol_dist_am FROM tdx_intraday_feat", s)
tds = [str(r[0]) for r in t.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date >= '20260212' ORDER BY trade_date").fetchall()]
nx = {d: tds[i+1] for i, d in enumerate(tds[:-1])}
def c2t(c): return f"{c}.SH" if str(c).startswith(("6","68","9")) else f"{c}.SZ"
px = {}
for d, tc, cl in t.execute("SELECT trade_date, ts_code, close FROM daily WHERE trade_date >= '20260212'").fetchall():
    px.setdefault(str(d), {})[tc] = float(cl)
rows = []
for _, r in feat.iterrows():
    dd, nxt = str(r['date']), nx.get(str(r['date']))
    tc = c2t(r['code'])
    c0, c1 = (px.get(dd, {}).get(tc), px.get(nxt, {}).get(tc)) if nxt else (None, None)
    ret = (c1/c0-1)*100 if c0 and c1 and c0 > 0 else None
    rows.append((r['date'], r['open30_ret'], r['tail30_ret'], r['vwap_dev'], r['rv_1m'], r['amp_intra'], r['vol_dist_am'], ret))
df = pd.DataFrame(rows, columns=['date','open30','tail30','vwap','rv1m','amp','voldist','ret'])
df = df.dropna(subset=['ret'])
print(f"样本: {len(df)} 行")

# ── 0. 相关性总览 ──
print("\n【相关性】(截面 Spearman 按日均值)")
for a, b in [('vwap','tail30'), ('amp','rv1m')]:
    ics = []
    for d, g in df.groupby('date'):
        if len(g) > 500:
            ics.append(g[a].corr(g[b], method='spearman'))
    print(f"  {a} vs {b}: 相关系数均值 {np.mean(ics):.3f}")

# ── 1. VWAP偏离度 vs 尾盘 ──
print("\n【1. VWAP偏离度与尾盘】")
v90 = df['vwap'].quantile(0.90)
ext = df[df['vwap'] > v90]
print(f"  VWAP偏离 > P90({v90:+.4f}) 占比 {len(ext)/len(df):.1%}, 其中尾盘上涨占比 {np.mean(ext['tail30']>0):.1%} (用户称 86.5%)")
neg = df[df['vwap'] < df['vwap'].quantile(0.10)]
print(f"  VWAP偏离 < P10: 尾盘上涨占比 {np.mean(neg['tail30']>0):.1%}")
# 交互: VWAP极端时 tail30 次日预测力
for cond, label in [(df['vwap'] > v90, 'VWAP正偏+P尾盘涨'), (df['vwap'] < df['vwap'].quantile(0.10), 'VWAP负偏+P尾盘跌')]:
    pass
hi_v = df[df['vwap'] > v90]
g1 = hi_v[hi_v['tail30'] > 0]['ret']; g0 = df[df['vwap'] <= v90][df['tail30'] > 0]['ret']
print(f"  VWAP正偏 + 尾盘涨: 次日均值 {g1.mean():+.2f}% (n={len(g1)})")
print(f"  普通VWAP + 尾盘涨: 次日均值 {g0.mean():+.2f}% (n={len(g0)})  → VWAP偏离增强tail30可信度?")

# ── 2. 振幅×波动 4象限 → 次日 ──
print("\n【2. 振幅×波动率交叉】(amp与rv1m相关0.79验证)")
amp_m, rv_m = df['amp'].median(), df['rv1m'].median()
for label, m in [('高振幅+高波动', (df['amp']>amp_m)&(df['rv1m']>rv_m)),
                 ('高振幅+低波动', (df['amp']>amp_m)&(df['rv1m']<=rv_m)),
                 ('低振幅+高波动', (df['amp']<=amp_m)&(df['rv1m']>rv_m)),
                 ('低振幅+低波动', (df['amp']<=amp_m)&(df['rv1m']<=rv_m))]:
    g = df[m]['ret']
    print(f"  {label}: n={len(g):>7} 次日均值 {g.mean():>+6.2f}% 中位 {g.median():>+6.2f}%")

# ── 3. 量价背离 (vol_dist_am=早盘量占比近似, 无总量特征) ──
print("\n【3. 量价背离】(注意: 特征表无成交总量, 用vol_dist_am高低近似量能集中度)")
vd_hi, vd_lo = df['voldist'].quantile(0.75), df['voldist'].quantile(0.25)
for label, m in [('量集中+尾盘涨', (df['voldist']>vd_hi)&(df['tail30']>0.005)),
                 ('量分散+尾盘涨', (df['voldist']<vd_lo)&(df['tail30']>0.005)),
                 ('量集中+尾盘跌', (df['voldist']>vd_hi)&(df['tail30']<-0.005)),
                 ('量分散+尾盘跌', (df['voldist']<vd_lo)&(df['tail30']<-0.005))]:
    g = df[m]['ret']
    print(f"  {label}: n={len(g):>6} 次日均值 {g.mean():>+6.2f}% 中位 {g.median():>+6.2f}%")

# ── 4. 开盘+尾盘 4象限 ──
print("\n【4. 开盘+尾盘 4象限】")
o_m, t_m = df['open30'].median(), df['tail30'].median()
quad = [('双强(开涨尾涨)', (df['open30']>o_m)&(df['tail30']>t_m)),
        ('双弱(开跌尾跌)', (df['open30']<o_m)&(df['tail30']<t_m)),
        ('冲高回落(开涨尾跌)', (df['open30']>o_m)&(df['tail30']<t_m)),
        ('低开高走(开跌尾涨)', (df['open30']<o_m)&(df['tail30']>t_m))]
for label, m in quad:
    g, sub = df[m]['ret'], df[m]
    print(f"  {label}: 占{len(g)/len(df):.1%} 次日均值 {g.mean():>+6.2f}% 中位 {g.median():>+6.2f}% 当日振幅均值 {sub['amp'].mean()*100:.2f}%")

# ── 5. VWAP×振幅交叉 → 尾盘 ──
print("\n【5. VWAP×振幅交叉 → 当日尾盘】")
vw_m, am_m = df['vwap'].median(), df['amp'].median()
for label, m in [('VWAP高+振幅大', (df['vwap']>vw_m)&(df['amp']>am_m)),
                 ('VWAP高+振幅小', (df['vwap']>vw_m)&(df['amp']<=am_m)),
                 ('VWAP低+振幅大', (df['vwap']<=vw_m)&(df['amp']>am_m)),
                 ('VWAP低+振幅小', (df['vwap']<=vw_m)&(df['amp']<=am_m))]:
    sub = df[m]
    print(f"  {label}: 占比{len(sub)/len(df):.1%} 当日mean_tail30 {sub['tail30'].mean():+.4f}")

# ── 6. 极端值 ──
print("\n【6. 极端值信号质量】")
for label, m in [('振幅>6%', df['amp']>0.06), ('RV_1m>5.0', df['rv1m']>5.0), ('尾盘急拉>1.5%', df['tail30']>0.015), ('尾盘杀跌<-1.5%', df['tail30']<-0.015)]:
    sub = df[m]
    print(f"  {label}: 占{len(sub)/len(df):.1%} 当日tail30均值 {sub['tail30'].mean():+.4f} 次日均值 {sub['ret'].mean():+.2f}%")

# ── 7. vol_dist_am 4档 ──
print("\n【7. 量能分布 4档】(vol_dist_am=早盘9:31-10:30量占比)")
for label, m in [('<0.30 集中', df['voldist']<0.30), ('0.30-0.45', (df['voldist']>=0.30)&(df['voldist']<0.45)),
                 ('0.45-0.60', (df['voldist']>=0.45)&(df['voldist']<0.60)), ('>0.60 高度分散', df['voldist']>=0.60)]:
    sub = df[m]
    print(f"  {label}: 占{len(sub)/len(df):.1%} 次日均值 {sub['ret'].mean():>+6.2f}% 中位 {sub['ret'].median():>+6.2f}%")
s.close(); t.close()
