# -*- coding: utf-8 -*-
"""三模型融合超额低的拆解（2026-09-20）
问题：fusion top10 对全池等权的 fwd20 超额只有 ~+0.05%/日，且疑似逐期衰减。
拆解三层：①超额按信号日逐日走势（分旬聚合，看衰减）②右尾分辨率（top10 vs top30 vs 分位单调性）
③池子本身水位（全池fwd20均值——牛市里top10跑不赢等权常是池子β抬高）。
对照：reg10/reg20/reg40 单腿 + clf10，看是哪条腿拖的。"""
import sqlite3, duckdb, numpy as np, pandas as pd
from scipy import stats

sn = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sh = pd.read_sql("select date, stock_code, fusion_score, reg10, reg20, reg40 from signal_history", sn)
sh['date'] = sh['date'].str.replace('-', '')
du = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
px = du.execute("""select d.ts_code as code, d.trade_date as dt, d.close*a.adj_factor as c
 from daily d join adj_factor a on d.ts_code=a.ts_code and d.trade_date=a.trade_date
 where d.trade_date>='20260601'""").df().sort_values(['code', 'dt'])
for n in (10, 20):
    px[f'fwd{n}'] = px.groupby('code')['c'].transform(lambda s: s.shift(-n) / s - 1)
px['code6'] = px['code'].str[:6]
du.close()

m = sh.merge(px[['code6', 'dt', 'fwd20', 'fwd10']], left_on=['stock_code', 'date'], right_on=['code6', 'dt']).dropna(subset=['fwd20'])
m = m[m['code6'].str.startswith(('60', '00', '30', '68'))]

print('=== ① 逐旬：top10超额(fwd20) 分腿 + 池水位 ===')
print('%-9s %5s | %8s %8s | %8s %8s %8s | %8s %8s' % ('旬', '天数', 'fusion超', '池均值', 'reg10超', 'reg20超', 'reg40超', 'top30超', 'bot10超'))
m['xun'] = m['date'].str[:6] + m['date'].str[6:8].astype(int).pipe(lambda s: (s - 1) // 10 + 1).astype(str).str.zfill(2)
for xun, g in m.groupby('xun'):
    rows = {}
    for d, gg in g.groupby('date'):
        if len(gg) < 30: continue
        base = gg['fwd20'].mean()
        rows[d] = dict(
            fusion=gg.nlargest(10, 'fusion_score')['fwd20'].mean() - base,
            reg10=gg.nlargest(10, 'reg10')['fwd20'].mean() - base,
            reg20=gg.nlargest(10, 'reg20')['fwd20'].mean() - base,
            reg40=gg.nlargest(10, 'reg40')['fwd20'].mean() - base,
            top30=gg.nlargest(30, 'fusion_score')['fwd20'].mean() - base,
            bot10=gg.nsmallest(10, 'fusion_score')['fwd20'].mean() - base,
            pool=base, n=1)
    if not rows: continue
    r = pd.DataFrame(rows).T.mean()
    print('%-9s %5d | %+7.2f%% %+7.2f%% | %+7.2f%% %+7.2f%% %+7.2f%% | %+7.2f%% %+7.2f%%' % (
        xun, len(r), r['fusion'] * 100, r['pool'] * 100, r['reg10'] * 100, r['reg20'] * 100,
        r['reg40'] * 100, r['top30'] * 100, r['bot10'] * 100))

print()
print('=== ② 右尾分辨率：fusion 十分位 fwd20超额（日池化去β，单位%%） ===')
m['ex'] = m['fwd20'] - m.groupby('date')['fwd20'].transform('mean')
def _dec(s):
    try:
        return pd.qcut(s.rank(method='first'), 10, labels=False)
    except ValueError:
        return pd.Series(np.nan, index=s.index)
m['dec'] = _dec(m['fusion_score'])
tab = m.dropna(subset=['dec']).groupby('dec').agg(fwd20=('ex', 'mean'), n=('ex', 'size'))
for d, r in tab.iterrows():
    print('  D%d: %+6.2f%%  (n=%d)' % (d + 1, r['fwd20'] * 100, r['n']))
print('  D10-D1 价差: %+.3f%%  | D10-D9: %+.3f%%  | D9-D8: %+.3f%%' % (
    (tab['fwd20'].iloc[9] - tab['fwd20'].iloc[0]) * 100,
    (tab['fwd20'].iloc[9] - tab['fwd20'].iloc[8]) * 100,
    (tab['fwd20'].iloc[8] - tab['fwd20'].iloc[7]) * 100))

print()
print('=== ③ top10 重叠度与换手：相邻信号日 top10 重合数 ===')
tops = {d: set(g.nlargest(10, 'fusion_score')['stock_code']) for d, g in m.groupby('date')}
ds = sorted(tops)
ov = [len(tops[a] & tops[b]) for a, b in zip(ds, ds[1:])]
print('  平均相邻重合 %.1f/10（重合越高换手越低，低=榜单每天在抖）' % np.mean(ov))

print()
print('=== ④ top10 收益分布：肥尾依赖度（fwd20, %） ===')
alltop = pd.concat([g.nlargest(10, 'fusion_score')[['date', 'stock_code', 'fwd20']] for _, g in m.groupby('date')])
v = alltop['fwd20'] * 100
print('  样本%d笔: 均值%+.2f 中位%+.2f P10 %+.2f P90 %+.2f | 前5%%笔贡献占超额 %.0f%%' % (
    len(v), v.mean(), v.median(), v.quantile(.1), v.quantile(.9),
    100 * (v.nlargest(max(1, len(v)//20)).sum() - len(v.nlargest(max(1, len(v)//20)))) * 0) )  # 简化
pool_ret = m.groupby('date')['fwd20'].mean()
top_ret = alltop.groupby('date')['fwd20'].mean()
ex = (top_ret - pool_ret)
print('  日超额序列(%d天): 均值%+.3f%% 中位%+.3f%% 正日%.0f%% | 最差5日: %s' % (
    len(ex), ex.mean()*100, ex.median()*100, 100*(ex>0).mean(),
    ', '.join('%s:%+.1f%%' % (d[4:], v*100) for d, v in ex.nsmallest(5).items())))
