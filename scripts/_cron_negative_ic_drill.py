# -*- coding: utf-8 -*-
"""负IC归因：验证窗逐日IC × 市场环境下钻（周粒度 + 涨跌分组 + 滞后相关性）"""
import duckdb, pandas as pd, numpy as np
from scipy import stats

c = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
idx = c.execute("""SELECT date, close FROM index_daily
    WHERE index_code='000852' AND date>='2025-11-01' ORDER BY date""").df()
c.close()
idx['date'] = pd.to_datetime(idx['date'].astype(str).str[:10].str.replace('-',''), format='%Y%m%d')
idx = idx.set_index('date')['close']
idx_ret = idx.pct_change()          # 中证1000当日收益
idx_5d = idx.pct_change(5)          # 前5日累计（入窗时环境动量）

a = pd.read_csv('/Users/zantao/.hermes/stockdb/analysis/ab_intraday/daily_ic_roll_A.csv')
b = pd.read_csv('/Users/zantao/.hermes/stockdb/analysis/ab_intraday/daily_ic_roll_B.csv')
for _d in (a, b):
    _d['date'] = pd.to_datetime(_d['date'].astype(str), format='%Y%m%d')
a = a.set_index('date')['ic']; b = b.set_index('date')['ic']
j = pd.concat([a.rename('A'), b.rename('B')], axis=1).dropna()
j['idx_ret'] = idx_ret.reindex(j.index)
j['idx_5d'] = idx_5d.reindex(j.index)
j['idx_5d_at_entry'] = idx_5d.reindex(j.index - pd.Timedelta(days=1))  # 特征日环境（约正）
j = j.dropna()
print(f"样本日 {len(j)} {j.index.min():%m-%d}~{j.index.max():%m-%d}")

print("\n== 按中证1000当日涨跌分组 ==")
up = j[j['idx_ret'] > 0]; dn = j[j['idx_ret'] <= 0]
for nm, g in (('上涨日', up), ('下跌日', dn)):
    print(f"{nm} n={len(g)}  A {g['A'].mean():+.4f}  B {g['B'].mean():+.4f}  B-A {(g['B']-g['A']).mean():+.4f}")

print("\n== 按特征日前5日环境（前期动量）分组 ==")
m5 = j['idx_5d_at_entry']
for nm, g in (('前5日涨(>2%)', j[m5 > 0.02]), ('前5日震荡', j[(m5 >= -0.02) & (m5 <= 0.02)]), ('前5日跌(<-2%)', j[m5 < -0.02])):
    if len(g): print(f"{nm} n={len(g)}  A {g['A'].mean():+.4f}  B {g['B'].mean():+.4f}")

print("\n== IC与环境的Rank相关（IC越低越负=反噬越强）==")
for col in ('idx_ret', 'idx_5d_at_entry'):
    rA, pA = stats.spearmanr(j['A'], j[col]); rB, pB = stats.spearmanr(j['B'], j[col])
    print(f"A_IC vs {col}: rho={rA:+.3f} p={pA:.4f} | B: rho={rB:+.3f} p={pB:.4f}")

print("\n== 周粒度（ISO周）==")
w = j.set_index(j.index.to_period('W')).groupby(level=0).agg(
    A=('A','mean'), B=('B','mean'), idx=('idx_ret','sum'), days=('A','size'))
w['B-A'] = w['B'] - w['A']
print(w.round(4).to_string())
# 周IC与周涨跌相关
rw, pw = stats.spearmanr(w['A'], w['idx'])
print(f"\n周IC(A) vs 周中证1000涨幅: rho={rw:+.3f} p={pw:.4f}")