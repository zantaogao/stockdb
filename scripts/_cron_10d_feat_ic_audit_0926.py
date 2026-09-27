"""10d 样本逐特征日截面 RankIC 时间序列审计（2026-09-26）。
特征名映射: f{j} -> PV_INDICES[j] 处 BASE_FEAT_NAMES 名。
输出: analysis/feat_ic_audit_0926/per_day.csv + 月度均值透视。
"""
import duckdb, numpy as np, pandas as pd, os
from scipy import stats

BASE = os.path.expanduser('~/.hermes/stockdb')
PV_INDICES = [0,1,2,3,5,6,7,10,11,12,13,14,15,16,17,18,19,23,24,25,26,27,28,29,30,32,33,34,35,36,37]
BASE_FEAT_NAMES = [
    'chg5','chg10','chg20','chg60','chg120',
    'd5','d10','d20','d60','d120',
    'bull1','bull2',
    'rr','std20','vr','pos','nh','vpc',
    'c1d','c3d',
    'ep','bp','ln_cap',
    'ex5','ex10','ex20',
    'skew20','kurt20',
    'dn_streak','up_ratio10',
    'vol_chg','rel_str',
    'kurt60','slope5','slope10','accel',
    'vp_shrink','vp_div',
]
FEAT_NAMES = [BASE_FEAT_NAMES[i] for i in PV_INDICES]
assert len(FEAT_NAMES) == 31, FEAT_NAMES

con = duckdb.connect()
df = con.execute(f"select * from read_parquet('{BASE}/analysis/retrain_20260926/samples_10d.parquet')").df()
con.close()
print('样本', len(df), df['date'].min(), df['date'].max(), flush=True)

rows = []
for d, g in df.groupby('date'):
    if len(g) < 500: continue
    y = g['y10'].to_numpy()
    rec = {'date': str(d)}
    for j in range(31):
        x = g[f'f{j}'].to_numpy()
        mask = np.isfinite(x) & np.isfinite(y)
        if mask.sum() < 500 or np.allclose(x[mask], x[mask][0]):
            rec[f'f{j}'] = np.nan; continue
        rec[f'f{j}'] = stats.spearmanr(x[mask], y[mask])[0]
    rows.append(rec)

ic = pd.DataFrame(rows)
ic['ym'] = ic['date'].str[:6]
out = f'{BASE}/analysis/feat_ic_audit_0926'
os.makedirs(out, exist_ok=True)
ic.to_csv(f'{out}/per_day.csv', index=False)

names = {f'f{j}': FEAT_NAMES[j] for j in range(31)}
month = ic.groupby('ym')[[f'f{j}' for j in range(31)]].mean()
month.index = [names[c] for c in month.columns] if False else month.index
month.columns = [names[c] for c in month.columns]
print('=== 月度日均截面IC（全样本 20220407~20260910）===')
print(month.round(4).to_string())
# 近12月 vs 训练早期均值对比
recent = month[month.index >= '202509']
early = month[(month.index >= '202204') & (month.index <= '202412')]
comp = pd.DataFrame({'早期均值(22-24)': early.mean(), '近12月均值(25-09~)': recent.mean()})
comp['差'] = comp['近12月均值(25-09~)'] - comp['早期均值(22-24)']
print('=== 衰减对比 ===')
print(comp.round(4).sort_values('差').to_string())
month.to_csv(f'{out}/month_mean.csv')
comp.to_csv(f'{out}/decay_compare.csv')
print('WROTE', out)
