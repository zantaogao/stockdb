# -*- coding: utf-8 -*-
"""fusion_v2 候选权重复验（2026-09-20，配对日差分口径）
上一轮网格用"对池均值"挑出 7reg10+3clf10 等候选，t值含日级市场噪音，假阳性风险未过闸。
本轮硬标准：对照 = reg10 直接 top10（reg10_solo 实盘口径）；候选榜单 − 对照榜单 **逐日配对差**，
NW-t：fwd10 尺 lag10、fwd20 尺 lag20。附分旬拆解 + 累计差曲线（看增益是否集中在个别天）。
候选：v2=8/2, 7/3, 5/5, clf10单腿, 现行fusion(0.2小数+0.3reg20+0.5reg40)。"""
import sqlite3, duckdb, numpy as np, pandas as pd

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
m['n10'] = m['clf10'].notna()
for k in ('reg10', 'clf10'):
    m['r_' + k] = m.groupby('date')[k].rank(pct=True)
m['r_clf10'] = m['r_clf10'].fillna(0.5)

def nw_t(x, lag):
    x = np.asarray(x, float); x = x[np.isfinite(x)]; n = len(x)
    if n < 5: return np.nan
    mu = x.mean(); xm = x - mu
    s = (xm @ xm) / n
    for l in range(1, lag + 1):
        s += 2 * (1 - l / (lag + 1)) * (xm[l:] @ xm[:-l]) / n
    return mu / np.sqrt(s / n)

cands = {'v2=8/2': 0.8, 'v2=7/3': 0.7, 'v2=5/5': 0.5, 'clf10单腿': 0.0, '现行fusion': None}
rows = []
for d, g in m.groupby('date'):
    if len(g) < 50: continue
    rec = {'date': d}
    ctrl = g.nlargest(10, 'reg10')
    rec['c10'] = ctrl['fwd10'].dropna().mean(); rec['c20'] = ctrl['fwd20'].dropna().mean()
    for name, w in cands.items():
        s = g['fs'] if w is None else (w * g['r_reg10'] + (1 - w) * g['r_clf10'])
        t = g.assign(_s=s).nlargest(10, '_s')
        k = name.replace('=', '').replace('/', '')[:6]
        rec[k + '10'] = t['fwd10'].dropna().mean(); rec[k + '20'] = t['fwd20'].dropna().mean()
        rec[k + 'ov'] = len(set(t['stock_code']) & set(ctrl['stock_code']))
    rows.append(rec)
r = pd.DataFrame(rows).sort_values('date').reset_index(drop=True)
def _xun(d):
    day = int(d[6:8]); return d[:6] + ('上' if day <= 10 else ('中' if day <= 20 else '下'))
r['ten'] = r['date'].map(_xun)
print('成熟日 %d | 对照=reg10直接top10: fwd10 %+.2f%% fwd20 %+.2f%%（绝对）' % (len(r), r.c10.mean()*100, r.c20.mean()*100))
print()
print('=== 配对日差分（候选top10 − 对照top10，同池同日，市场噪音对消）===')
keys = {}
for name in cands:
    k = name.replace('=', '').replace('/', '')[:6]; keys[name] = k
    d10 = r[k + '10'] - r['c10']; d20 = r[k + '20'] - r['c20']
    print('%-10s 重合%4.1f/10 | fwd10差 %+6.3f%% (t%+5.2f) 差>0 %2d/%d | fwd20差 %+6.3f%% (t%+5.2f) 差>0 %2d/%d' % (
        name, r[k + 'ov'].mean(),
        d10.mean()*100, nw_t(d10, 10), (d10 > 0).sum(), len(d10),
        d20.dropna().mean()*100, nw_t(d20, 20), (d20 > 0).sum(), d20.notna().sum()))
print()
print('=== 分旬 fwd10 配对差（%%）===')
hdr = '旬        n  ' + ' '.join('%-10s' % c for c in cands)
print(hdr)
for t, gg in r.groupby('ten'):
    line = '%-9s %2d  ' % (t, len(gg))
    for name in cands:
        k = keys[name]
        line += '%-10s' % ('%+.2f' % ((gg[k+'10']-gg['c10']).mean()*100))
    print(line)
print()
print('=== 累计配对差曲线 fwd10（每5日，%）：看增益是匀速还是靠个别天 ===')
for name in cands:
    k = keys[name]
    cum = (r[k+'10']-r['c10']).cumsum()
    print('%-10s ' % name + ' '.join('%+.1f' % v for v in cum[::5]))
