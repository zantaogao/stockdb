# -*- coding: utf-8 -*-
# ≥80池内排序键横评（2026-09-20）
# 池=cmmr_score>=80；候选键全部测：档内日rank IC(对fwd20) + 高低半劈分
import duckdb, sqlite3, numpy as np, pandas as pd
from scipy import stats

sn = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
keys = ['fusion_score','reg10','reg20','reg40','fusion_score_cmmr','deviation120','ma40_slope',
        'gtja_score','cls27_prob','old_score','lstm','reg_pred','reg10_pred','reg40_pred','final_score','fusion_avg']
cols = ','.join(keys)
sh = pd.read_sql(f"select stock_code, date, cmmr_score, {cols} from signal_history where cmmr_score>=80", sn)
sh['date'] = sh['date'].astype(str).str.replace('-','').str[:8]
print('池行数', len(sh), '天', sh['date'].nunique())

du = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
px = du.execute("""select d.ts_code as code, d.trade_date as dt, d.close*a.adj_factor as c,
 d.vol as v, d.close as rawc, d.pre_close as rawpc
 from daily d join adj_factor a on d.ts_code=a.ts_code and d.trade_date=a.trade_date
 where d.trade_date>='20260401'""").df().sort_values(['code','dt'])
px['fwd20'] = px.groupby('code')['c'].transform(lambda s: s.shift(-20)/s-1)
g = px.groupby('code')
px['turn5'] = g['v'].transform(lambda s: s.rolling(5).mean())
px['vr20'] = px['v']/g['v'].transform(lambda s: s.rolling(20).mean())
px['gap'] = px['rawc']/px['rawpc']-1  # 当日涨跌近似（未复权，%级键够）
px['code6'] = px['code'].str[:6]

m = sh.merge(px[['code6','dt','fwd20','vr20','gap']], left_on=['stock_code','date'], right_on=['code6','dt'])
m = m.dropna(subset=['fwd20'])
print('成熟样本', len(m), '天', m['date'].nunique())
m['vr_rank'] = m.groupby('date')['vr20'].rank(pct=True)
m['gap_rank'] = -m.groupby('date')['gap'].rank(pct=True)  # 池内跌得多的排前（接刀假设）

mkt = px.groupby('dt')['fwd20'].mean()
m['ex'] = m['fwd20'] - m['dt'].map(mkt)

cands = keys + ['vr_rank','gap_rank']
rows=[]
for k in cands:
    sub = m.dropna(subset=[k])
    if sub.empty: continue
    ics, hs = [], []
    for d, g in sub.groupby('date'):
        if len(g) < 30: continue
        ic = stats.spearmanr(g[k], g['fwd20']).statistic
        ics.append(ic)
        med = g[k].median()
        hi = g[g[k]>med]['ex'].mean(); lo = g[g[k]<=med]['ex'].mean()
        if pd.notna(hi) and pd.notna(lo): hs.append(hi-lo)
    if len(ics) < 8: 
        print('%-18s 成熟天数不足(%d) 跳过' % (k, len(ics))); continue
    ics = np.array(ics); hs = np.array(hs)
    n = len(ics); sd = ics.std(ddof=1)
    se = sd/np.sqrt(n) * np.sqrt(1+2*sum(np.corrcoef(ics[:-j],ics[j:])[0,1] for j in (1,2,3))/3)  # 粗糙NW修正
    print('%-18s 天数%2d | 档内IC均值%+.4f 为正%d/%d ICIR%+.2f | 高低半日差均 %+5.2fpp 正%d/%d' % (
        k, n, ics.mean(), (ics>0).sum(), n, ics.mean()/sd if sd else 0,
        hs.mean()*100, (hs>0).sum(), len(hs)))
