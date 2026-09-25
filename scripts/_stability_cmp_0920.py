# -*- coding: utf-8 -*-
"""稳定横评（2026-09-20）：中枢版 vs 三模型fusion vs CMMR vs clf10/v4d/v4big
统一口径：日截面 Spearman IC（对 fwd20 复权收益）+ top10超额（vs 全池等权）
统计：均值、NW(lag10) t、正日占比。成熟窗=各榜信号日∩fwd20已走完（数据尾20260918）。"""
import sqlite3, duckdb, numpy as np, pandas as pd
from scipy import stats

sn = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
zh = pd.read_sql("select date, stock_code, score from fusion_center_signals", sn)
sh = pd.read_sql("select date, stock_code, fusion_score, cmmr_score, fusion_score_cmmr from signal_history", sn)
c10 = pd.read_sql("select date, code, score from shadow_clf10_scores", sn)
v4d = pd.read_sql("select date, code, score from shadow_v4d_scores", sn)
for df in (zh, sh, c10, v4d):
    df['date'] = df['date'].astype(str).str.replace('-', '')[:8] if False else df['date'].astype(str).str.replace('-', '')

du = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
px = du.execute("""select d.ts_code as code, d.trade_date as dt, d.close*a.adj_factor as c
 from daily d join adj_factor a on d.ts_code=a.ts_code and d.trade_date=a.trade_date
 where d.trade_date>='20260601'""").df().sort_values(['code', 'dt'])
px['fwd20'] = px.groupby('code')['c'].transform(lambda s: s.shift(-20) / s - 1)
px['code6'] = px['code'].str[:6]
px = px[px['code6'].str.startswith(('60', '00', '30', '68'))]  # 剔除北交所等
du.close()

mkt = px.groupby('dt')['fwd20'].mean()

def nw_t(x, lag=10):
    x = np.asarray(x, float); x = x[np.isfinite(x)]; n = len(x)
    if n < 5: return np.nan
    m = x.mean(); xm = x - m
    s = (xm @ xm) / n
    for l in range(1, lag + 1):
        s += 2 * (1 - l / (lag + 1)) * (xm[l:] @ xm[:-l]) / n
    return m / np.sqrt(s / n)

boards = {
    '中枢版score':   (zh, 'stock_code', 'score'),
    '三模型fusion':  (sh, 'stock_code', 'fusion_score'),
    'CMMR':         (sh, 'stock_code', 'cmmr_score'),
    'fusion_cmmr':  (sh, 'stock_code', 'fusion_score_cmmr'),
    'clf10影子':    (c10, 'code', 'score'),
    'v4d影子':      (v4d, 'code', 'score'),
}
print('%-14s %4s %8s %8s %6s | %8s %8s' % ('榜', '天数', 'IC均值', 'NW-t', '正日%', 'top10超', '超Win%'))
for name, (df, ccol, vcol) in boards.items():
    m = df.merge(px[['code6', 'dt', 'fwd20']], left_on=[ccol, 'date'], right_on=['code6', 'dt'])
    m = m.dropna(subset=['fwd20', vcol])
    ics, exs, wins = [], [], []
    for d, g in m.groupby('date'):
        if len(g) < 30: continue
        ics.append(stats.spearmanr(g[vcol], g['fwd20']).statistic)
        base = g['fwd20'].mean()
        top = g.nlargest(10, vcol)['fwd20'].mean()
        exs.append(top - base); wins.append(1 if top - base > 0 else 0)
    if len(ics) < 5:
        print('%-14s 成熟不足(%d)' % (name, len(ics))); continue
    exs = np.array(exs)
    print('%-14s %4d %+8.4f %+8.2f %5.0f%% | %+7.3f%% %6.0f%%' % (
        name, len(ics), np.mean(ics), nw_t(ics), 100 * np.mean(np.array(ics) > 0),
        exs.mean(), 100 * np.mean(np.array(wins) > 0)))
