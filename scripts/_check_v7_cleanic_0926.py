# v7 IC 是否被 y40 极值抬高：去极值重算验证段 IC + 单调性 (2026-09-26)
import json, numpy as np, pandas as pd
from pathlib import Path
from scipy import stats
import lightgbm as lgb
B = Path.home()/'.hermes/stockdb/analysis/retrain_20260926'
df = pd.read_parquet(B/'samples_40d_v7.parquet'); df['date'] = df['date'].astype(str)
model = lgb.Booster(model_str=(B/'lgb_reg_40d_v7.txt').read_text())
stats_dict = json.load(open(B/'v40_v7_stats.json'))
feats = ['f%d'%j for j in range(26)] + ['f31','f32','f33','f34']
dts = np.sort(df['date'].unique()); split = dts[int(len(dts)*0.8)]
va = df[df['date'] >= split].reset_index(drop=True)
X = np.column_stack([((np.clip(va[f].to_numpy(float), stats_dict[f'feat_{j}']['low'], stats_dict[f'feat_{j}']['high'])
    - stats_dict[f'feat_{j}']['mean']) / stats_dict[f'feat_{j}']['std']) for j, f in enumerate(feats)])
X = np.nan_to_num(X, nan=0.0)
pred = model.predict(X)
y = va['y40'].to_numpy(float); d = va['date'].to_numpy()
for name, mask in [('全样本', np.ones(len(y), bool)), ('剔|y|>99.5%分位', np.abs(y) <= np.percentile(np.abs(y), 99.5))]:
    ics = []
    for dd in np.unique(d[mask]):
        m = mask & (d == dd)
        if m.sum() >= 200: ics.append(stats.spearmanr(pred[m], y[m])[0])
    ics = np.array([i for i in ics if np.isfinite(i)])
    pairs = sorted(zip(pred[mask], y[mask]), key=lambda x: x[0]); k = len(pairs)//10
    dec = [np.mean([r for _,r in pairs[i*k:(i+1)*k]])*100 for i in range(9)] + [np.mean([r for _,r in pairs[9*k:]])*100]
    print(f'{name}: 日均IC {ics.mean():+.4f} 正IC占比 {(ics>0).mean()*100:.0f}% 天数{len(ics)}')
    print('  十分组:', ' '.join(f'D{i+1}:{v:+.1f}%' for i, v in enumerate(dec)))
