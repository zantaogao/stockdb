# -*- coding: utf-8 -*-
"""自审：B/C/D 岗位结论是真是假（2026-09-20）
三道关卡：
 ① NW-t 用足滞后：fwd20 尺 lag=20（严格），fwd10 尺 lag=10
 ② 配对日差分：D/B/C 与对照(=reg10直接top10) 逐日配对差 NW-t——比"各自对池均值"更硬
 ③ 分旬拆解 + 换仓解剖：D 与对照 top10 逐日重合几只、增量到底来自哪几天"""
import sqlite3, duckdb, numpy as np, pandas as pd

sn = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sh = pd.read_sql("select date, stock_code, reg10, reg20, reg40 from signal_history", sn)
sh['date'] = sh['date'].str.replace('-', '')
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

def nw_t(x, lag):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    n = len(x)
    if n < 5: return np.nan
    m_ = x.mean(); xm = x - m_
    s = (xm @ xm) / n
    for l in range(1, lag + 1):
        s += 2 * (1 - l / (lag + 1)) * (xm[l:] @ xm[:-l]) / n
    return m_ / np.sqrt(s / n)

rows = []
for d, g in m.groupby('date'):
    if len(g) < 50: continue
    b10 = g['fwd10'].dropna().mean(); b20 = g['fwd20'].dropna().mean()
    ctrl = g.nlargest(10, 'reg10')
    D = g.nlargest(50, 'reg10').nlargest(10, 'reg40')
    B = g.nlargest(30, 'reg10').nlargest(10, 'reg40')   # B统一用reg40排雷（reg20变体另记）
    B2 = g.nlargest(30, 'reg10').nlargest(10, 'reg20')
    C = g.nsmallest(10, 'reg40')                        # 被否决票
    ov = len(set(D['stock_code']) & set(ctrl['stock_code']))
    rows.append(dict(date=d,
        ctrl10=ctrl['fwd10'].dropna().mean() - b10, D10=D['fwd10'].dropna().mean() - b10,
        B10=B['fwd10'].dropna().mean() - b10, B2_10=B2['fwd10'].dropna().mean() - b10,
        C10=C['fwd10'].dropna().mean() - b10,
        ctrl20=ctrl['fwd20'].dropna().mean() - b20, D20=D['fwd20'].dropna().mean() - b20,
        B20=B['fwd20'].dropna().mean() - b20, B2_20=B2['fwd20'].dropna().mean() - b20,
        C20=C['fwd20'].dropna().mean() - b20, ov=ov, nD=len(D)))
r = pd.DataFrame(rows).sort_values('date').reset_index(drop=True)
def _xun(d):
    day = int(d[6:8])
    return d[:6] + ('上' if day <= 10 else ('中' if day <= 20 else '下'))
r['ten'] = r['date'].map(_xun)
print('成熟日 %d，D与对照top10平均重合 %.1f/10（每天实际只换 %.1f 只）' % (len(r), r.ov.mean(), 10 - r.ov.mean()))
print()
print('=== ① 各策略对池均值（左=fwd10 lag10, 右=fwd20 lag20 严格）===')
KMAP = {'ctrl': '对照 reg10 top10', 'D': 'D双门', 'B': 'B排雷(reg40)', 'B2_': 'B2排雷(reg20)', 'C': 'C被否决bot10'}
for k, lab in KMAP.items():
    print('  %-16s fwd10 %+6.2f%% (t%+5.2f) | fwd20 %+6.2f%% (t%+5.2f)' % (
        lab, r[k+'10'].mean()*100, nw_t(r[k+'10'], 10), r[k+'20'].mean()*100, nw_t(r[k+'20'], 20)))
print()
print('=== ② 配对日差分（策略−对照，剔除日级市场噪音后 D/B 还有没有增量）===')
for k in ('D', 'B', 'B2_'):
    d10 = r[k+'10'] - r['ctrl10']; d20 = r[k+'20'] - r['ctrl20']
    print('  %-4s−对照  fwd10: 日均差 %+6.3f%% (t%+5.2f) 差>0 %2d/%d | fwd20: 日均差 %+6.3f%% (t%+5.2f) 差>0 %2d/%d' % (
        k, d10.mean()*100, nw_t(d10, 10), (d10>0).sum(), len(d10), d20.mean()*100, nw_t(d20, 20), (d20>0).sum(), len(d20)))
print()
print('=== ③ 分旬（fwd20超额 对池；对照 vs D）===')
for t, g in r.groupby('ten'):
    print('  %-8s n=%2d  对照 %+7.2f%%  D %+7.2f%%  D−对照 %+7.2f%%  否决票(bot10) %+7.2f%%' % (
        t, len(g), g.ctrl20.mean()*100, g.D20.mean()*100, (g.D20-g.ctrl20).mean()*100, g.C20.mean()*100))
print()
print('=== ④ D−对照 逐日差 TOP5/BOTTOM5 天（看增量是否集中）===')
r['dd'] = r.D20 - r.ctrl20
srt = r.sort_values('dd')
for _, x in pd.concat([srt.tail(5), srt.head(5)]).iterrows():
    print('   %s  D−对照 %+7.2f%%（当日换 %d 只）' % (x['date'], x.dd, 10 - x.ov))
cum = r.sort_values('date')['dd'].cumsum()
print('   累计差曲线(每5日): ' + ' '.join('%+.1f' % v for v in cum[::5]))
