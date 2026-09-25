# -*- coding: utf-8 -*-
"""fusion 权重怎么分（2026-09-20 对拍，不动生产）
背景：现行 fusion=0.2reg10(小数口径,实际贡献≈0.08%)+0.3reg20+0.5reg40 —— reg10 名存实亡。
做法：四条腿（reg10/reg20/reg40/clf10）各自先做**日截面 rank(pct)** 消量纲，再在单纯形上
网格搜权重（步长0.1），口径=成熟日 top10 fwd20 超额 + 日超额序列 NW(lag10) t + 日IC。
防过拟合：24 个成熟日太少，网格结果只当方向；同时报 前段(7月)/后段(8月) 分窗一致性。"""
import sqlite3, duckdb, itertools, numpy as np, pandas as pd
from scipy import stats

sn = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sh = pd.read_sql("select date, stock_code, reg10, reg20, reg40 from signal_history", sn)
sh['date'] = sh['date'].str.replace('-', '')
c10 = pd.read_sql("select date, code, score from shadow_clf10_scores", sn)
c10['date'] = c10['date'].str.replace('-', '')
du = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
px = du.execute("""select d.ts_code as code, d.trade_date as dt, d.close*a.adj_factor as c
 from daily d join adj_factor a on d.ts_code=a.ts_code and d.trade_date=a.trade_date
 where d.trade_date>='20260601'""").df().sort_values(['code', 'dt'])
px['fwd20'] = px.groupby('code')['c'].transform(lambda s: s.shift(-20) / s - 1)
px['code6'] = px['code'].str[:6]
du.close()

m = sh.merge(px[['code6', 'dt', 'fwd20']], left_on=['stock_code', 'date'], right_on=['code6', 'dt'])
m = m.dropna(subset=['fwd20', 'reg10', 'reg20', 'reg40'])
m = m[m['code6'].str.startswith(('60', '00', '30', '68'))]
# clf10 只有 2026-07-15 起回补过，且票池略小；左连+rank 在 clf10 缺失票上给当日均位
c10 = c10.rename(columns={'score': 'clf10', 'code': 'stock_code'})
m = m.merge(c10, on=['date', 'stock_code'], how='left')
for k in ('reg10', 'reg20', 'reg40', 'clf10'):
    m['r_' + k] = m.groupby('date')[k].rank(pct=True)
m['r_clf10'] = m['r_clf10'].fillna(0.5)  # clf10 未覆盖票给当日均位，不惩罚也不奖励

mkt = m.groupby('date')['fwd20'].transform('mean')
m['ex'] = m['fwd20'] - mkt

def nw_t(x, lag=10):
    x = np.asarray(x, float); n = len(x)
    m_ = x.mean(); xm = x - m_
    s = (xm @ xm) / n
    for l in range(1, lag + 1):
        s += 2 * (1 - l / (lag + 1)) * (xm[l:] @ xm[:-l]) / n
    return m_ / np.sqrt(s / n)

# ——向量化预计算：每日腿矩阵/超额一次性拉成 numpy，网格只算加权和取top10
days = sorted(m['date'].unique())
day_idx = {d: i for i, d in enumerate(days)}
m['_di'] = m['date'].map(day_idx)
LEGS = ['r_reg10', 'r_reg20', 'r_reg40', 'r_clf10']
bmat, bex, bfwd = {}, {}, {}
for d, g in m.groupby('_di'):
    if len(g) < 30: continue
    bmat[d] = g[LEGS].to_numpy(dtype=float)
    bex[d] = g['ex'].to_numpy(dtype=float)
    bfwd[d] = g['fwd20'].to_numpy(dtype=float)

def evaluate(w10, w20, w40, wc, top=10):
    W = np.array([w10, w20, w40, wc])
    d_ex, ics = [], []
    for d in sorted(bmat):
        s = bmat[d] @ W
        k = np.argpartition(-s, top)[:top]
        d_ex.append(bex[d][k].mean())
        ics.append(stats.spearmanr(s, bfwd[d]).statistic)
    e = np.array(d_ex)
    return e.mean(), nw_t(e), np.mean(ics), len(e)

print('=== 基线：现行 fusion 公式（reg 原始值直加，reg10名存实亡）===')
sh2 = pd.read_sql("select date, stock_code, fusion_score as fs from signal_history", sn)
sh2['date'] = sh2['date'].str.replace('-', '')
mm = m.merge(sh2, on=['date', 'stock_code'])
d_ex = []
for d, g in mm.groupby('date'):
    d_ex.append(g.nlargest(10, 'fs')['ex'].mean())
e = np.array(d_ex)
print('现行fusion: top10超额均值 %+.3f%% NW-t %+.2f 成熟日 %d' % (e.mean() * 100, nw_t(e), len(e)))

print()
print('=== 单腿（rank 化后，防"哪条腿有货"误判）===')
for k in ('reg10', 'reg20', 'reg40', 'clf10'):
    a, b, c, n = evaluate(*{'reg10': (1, 0, 0, 0), 'reg20': (0, 1, 0, 0),
                            'reg40': (0, 0, 1, 0), 'clf10': (0, 0, 0, 1)}[k])
    print('  r_%-6s 超额 %+6.3f%% NW-t %+5.2f IC %+.4f' % (k, a * 100, b, c))

print()
print('=== 网格（步长0.1，全部24成熟日）TOP 12 ===')
rows = []
for w in itertools.product(range(11), repeat=4):
    if sum(w) != 10: continue
    a, b, c, n = evaluate(*[x / 10 for x in w])
    rows.append((w, a, b, c, n))
rows.sort(key=lambda r: -r[2])   # 按 NW-t
print('%-16s %8s %7s %8s' % ('w(10/20/40/clf)', '超额%', 'NW-t', 'IC'))
for w, a, b, c, n in rows[:12]:
    print('%-16s %+8.3f %+7.2f %+8.4f' % ('%d/%d/%d/%d' % w, a * 100, b, c))

print()
print('=== 分窗一致性：网格TOP6 + 现行，前段(7月) vs 后段(8月+) ===')
mm2 = m.copy()
def window_eval(w, lo, hi):
    w10, w20, w40, wc = [x / 10 for x in w]
    s = w10 * mm2.r_reg10 + w20 * mm2.r_reg20 + w40 * mm2.r_reg40 + wc * mm2.r_clf10
    d_ex = []
    for d, g in mm2.assign(s=s).groupby('date'):
        if not (lo <= d <= hi) or len(g) < 30: continue
        d_ex.append(g.nlargest(10, 's')['ex'].mean())
    return np.mean(d_ex) * 100 if d_ex else np.nan, len(d_ex)
print('%-16s %-16s %-16s' % ('权重', '7月(n,超额%)', '8月+(n,超额%)'))
cands = [r[0] for r in rows[:6]] + [(2, 3, 5, 0)]
for w in cands:
    a1, n1 = window_eval(w, '20260701', '20260731')
    a2, n2 = window_eval(w, '20260801', '20260930')
    print('%-16s %6.1f%% (n=%d)     %6.1f%% (n=%d)' % ('%d/%d/%d/%d' % w, a1, n1, a2, n2))
