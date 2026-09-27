"""特征逐日截面 RankIC 审计 v2 — 10d 样本全 31 维正确命名 + 缺失兜底排查。
输出 analysis/feat_ic_audit_0926/v2_*.csv
"""
import duckdb, numpy as np, pandas as pd, os
from scipy import stats

BASE = os.path.expanduser('~/.hermes/stockdb')
PV_INDICES = [0,1,2,3,5,6,7,10,11,12,13,14,15,16,17,18,19,23,24,25,26,27,28,29,30,32,33,34,35,36,37]
B = ['chg5','chg10','chg20','chg60','chg120','d5','d10','d20','d60','d120','bull1','bull2',
     'rr','std20','vr','pos','nh','vpc','c1d','c3d','ep','bp','ln_cap','ex5','ex10','ex20',
     'skew20','kurt20','dn_streak','up_ratio10','vol_chg','rel_str','kurt60','slope5','slope10',
     'accel','vp_shrink','vp_div']
NAMES = [B[i] for i in PV_INDICES]  # f0..f30
print('f23→', NAMES[23], ' f25→', NAMES[25])

con = duckdb.connect()
cols = ['date'] + [f'f{j}' for j in range(31)] + ['y10']
df = con.execute(f"select {','.join(cols)} from read_parquet('{BASE}/analysis/retrain_20260926/samples_10d.parquet')").df()
con.close()
print('样本', len(df), df.date.min(), df.date.max())

rows = []
for d, g in df.groupby('date'):
    if len(g) < 500: continue
    y = g['y10'].to_numpy()
    rec = {'date': str(d)}
    for j in range(31):
        x = g[f'f{j}'].to_numpy()
        mask = np.isfinite(x) & np.isfinite(y)
        if mask.sum() < 500 or np.unique(x[mask]).size < 10:
            rec[NAMES[j]] = np.nan
        else:
            rec[NAMES[j]] = stats.spearmanr(x[mask], y[mask])[0]
    rows.append(rec)
ic = pd.DataFrame(rows); ic['ym'] = ic['date'].str[:6]
out = f'{BASE}/analysis/feat_ic_audit_0926'

month = ic.groupby('ym')[[n for n in NAMES]].mean()
month.to_csv(f'{out}/v2_month_mean.csv')

recent = ic[ic['date'] >= '20250901']
summ = []
for n in NAMES:
    v = recent[n].dropna()
    t, p = stats.ttest_1samp(v, 0)
    summ.append({'feat': n, '近12月日均IC': round(float(v.mean()),4), 'p': round(float(p),4),
                 '正IC天占比': round(float((v>0).mean()),3), 'n天': len(v)})
s = pd.DataFrame(summ).sort_values('近12月日均IC')
print('=== 近12月(20250901~20260910) 单特征截面RankIC ===')
print(s.to_string(index=False))
s.to_csv(f'{out}/v2_recent_summary.csv', index=False)

# 月度矩阵打印（估值/超额/趋势重点）
key = ['ep','bp','ln_cap','ex5','ex10','ex20','chg5','chg10','chg20','d5','d10','d20','vol_chg','nh','rel_str','slope5','slope10','accel','c1d','c3d']
print('=== 月度日均IC(关键维) ===')
print(month[key].round(4).to_string())
