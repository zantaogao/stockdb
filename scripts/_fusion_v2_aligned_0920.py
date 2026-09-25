# -*- coding: utf-8 -*-
"""fusion_v2 权重对拍·窗口对齐版（2026-09-20）
reg10/clf10 都是10日口径模型，前测用fwd20是错配。本脚本 fwd10 与 fwd20 双尺并报：
- 单腿 + 候选权重（rank化）top10 超额、NW-t
- 顺带报 top10 相邻日重合（10日窗口下换手指望）"""
import sqlite3, duckdb, numpy as np, pandas as pd
from scipy import stats

sn = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sh = pd.read_sql("select date, stock_code, reg10, reg20, reg40, fusion_score as fs from signal_history", sn)
sh['date'] = sh['date'].str.replace('-', '')
c10 = pd.read_sql("select date, code, score from shadow_clf10_scores", sn)
c10['date'] = c10['date'].str.replace('-', '')
c10 = c10.rename(columns={'code': 'stock_code', 'score': 'clf10'})
du = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
px = du.execute("""select d.ts_code as code, d.trade_date as dt, d.close*a.adj_factor as c
 from daily d join adj_factor a on d.ts_code=a.ts_code and d.trade_date=a.trade_date
 where d.trade_date>='20260601'""").df().sort_values(['code', 'dt'])
for n in (10, 20):
    px[f'fwd{n}'] = px.groupby('code')['c'].transform(lambda s: s.shift(-n) / s - 1)
px['code6'] = px['code'].str[:6]
du.close()

m = sh.merge(px[['code6', 'dt', 'fwd10', 'fwd20']], left_on=['stock_code', 'date'], right_on=['code6', 'dt'])
m = m.dropna(subset=['fwd10', 'reg10'])
m = m[m['code6'].str.startswith(('60', '00', '30', '68'))]
m = m.merge(c10, on=['date', 'stock_code'], how='left')
for k in ('reg10', 'reg20', 'reg40', 'clf10'):
    m['r_' + k] = m.groupby('date')[k].rank(pct=True)
m['r_clf10'] = m['r_clf10'].fillna(0.5)

def nw_t(x, lag=10):
    x = np.asarray(x, float); n = len(x)
    m_ = x.mean(); xm = x - m_
    s = (xm @ xm) / n
    for l in range(1, lag + 1):
        s += 2 * (1 - l / (lag + 1)) * (xm[l:] @ xm[:-l]) / n
    return m_ / np.sqrt(s / n)

LEGS = ['r_reg10', 'r_reg20', 'r_reg40', 'r_clf10']
cands = {'reg10单腿': (1, 0, 0, 0), 'clf10单腿': (0, 0, 0, 1),
         'v2=7reg10+3clf10': (0.7, 0, 0, 0.3), 'v2=8reg10+2clf10': (0.8, 0, 0, 0.2),
         'v2=5/5': (0.5, 0, 0, 0.5), '现行fusion(对照)': None}
for scale in (10, 20):
    col = f'fwd{scale}'
    m['ex'] = m[col] - m.groupby('date')[col].transform('mean')
    print(f'=== 尺子: {col}（top10对全池等权超额）===')
    for name, w in cands.items():
        if w is None:
            s = m['fs']
        else:
            s = sum(wi * m[l] for wi, l in zip(w, LEGS))
        d_ex = [g.nlargest(10, '_s')['ex'].dropna().mean() for _, g in m.assign(_s=s).groupby('date')]
        d_ex = [x for x in d_ex if np.isfinite(x)]
        e = np.array(d_ex)
        print('  %-18s 超额 %+6.3f%% NW-t %+5.2f 正日 %2d/%d' % (
            name, e.mean() * 100, nw_t(e), (e > 0).sum(), len(e)))
    # top10 相邻日重合
    tops = {d: set(g.nlargest(10, '_s')['stock_code']) for d, g in
            m.assign(_s=m.r_reg10 * 0.7 + m.r_clf10 * 0.3).groupby('date')}
    ds = sorted(tops)
    ov = np.mean([len(tops[a] & tops[b]) for a, b in zip(ds, ds[1:])])
    print('  v2榜单相邻日重合 %.1f/10（10日持有→可隔窗整批换，重合低不必然=坏，持满窗即可）' % ov)
