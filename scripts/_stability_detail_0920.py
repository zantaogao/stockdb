# -*- coding: utf-8 -*-
"""横评逐日明细：中枢/clf10/fusion 三个榜的日IC分布 + lag19 NW + 非重叠周采样稳健性"""
import sqlite3, duckdb, numpy as np, pandas as pd
from scipy import stats

sn = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
zh = pd.read_sql("select date, stock_code, score from fusion_center_signals", sn)
sh = pd.read_sql("select date, stock_code, fusion_score from signal_history", sn)
c10 = pd.read_sql("select date, code, score from shadow_clf10_scores", sn)
zh['date'] = zh['date'].str.replace('-', ''); sh['date'] = sh['date'].str.replace('-', ''); c10['date'] = c10['date'].str.replace('-', '')

du = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
px = du.execute("""select d.ts_code as code, d.trade_date as dt, d.close*a.adj_factor as c
 from daily d join adj_factor a on d.ts_code=a.ts_code and d.trade_date=a.trade_date
 where d.trade_date>='20260601'""").df().sort_values(['code', 'dt'])
px['fwd20'] = px.groupby('code')['c'].transform(lambda s: s.shift(-20) / s - 1)
px['code6'] = px['code'].str[:6]
du.close()

def nw_t(x, lag):
    x = np.asarray(x, float); n = len(x)
    m = x.mean(); xm = x - m
    s = (xm @ xm) / n
    for l in range(1, lag + 1):
        s += 2 * (1 - l / (lag + 1)) * (xm[l:] @ xm[:-l]) / n
    return m / np.sqrt(s / n)

for name, df, ccol, vcol in [('中枢', zh, 'stock_code', 'score'), ('fusion', sh, 'stock_code', 'fusion_score'), ('clf10', c10, 'code', 'score')]:
    m = df.merge(px[['code6', 'dt', 'fwd20']], left_on=[ccol, 'date'], right_on=['code6', 'dt']).dropna(subset=['fwd20'])
    ics = {}
    for d, g in m.groupby('date'):
        if len(g) < 30: continue
        ics[d] = stats.spearmanr(g[vcol], g['fwd20']).statistic
    ds = sorted(ics); v = np.array([ics[d] for d in ds])
    print('==', name, '成熟日', len(v), ' IC min/median/max: %.3f / %.3f / %.3f' % (v.min(), np.median(v), v.max()))
    print('   逐日:', ' '.join('%s:%+.2f' % (d[4:], x) for d, x in zip(ds, v)))
    print('   NW lag10 t=%.2f | NW lag19 t=%.2f' % (nw_t(v, 10), nw_t(v, 19)))
    # 非重叠：每20交易日取1个
    nonoverlap = v[::20]
    print('   非重叠采样(n=%d): %s' % (len(nonoverlap), ' '.join('%+.3f' % x for x in nonoverlap)))
