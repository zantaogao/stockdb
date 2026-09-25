# -*- coding: utf-8 -*-
"""影子链终训：B 模型(31基础+9日内)全样本训练 + 导出标准化 stats 供 Mac 复刻打分
- 全样本训练（不分折），早停集=最后10个交易日（这是唯一不进训练的数据）
- 每列 clip(lo,hi)+zscore 的 stats 全部来自早停集之前的样本 → 存 stats.json
- 输出: model_B_final.txt, stats.json (Mac 影子打分脚本逐字复刻此变换)
"""
import json, time
import numpy as np, pandas as pd
import lightgbm as lgb
from pathlib import Path

BASE = Path(r'C:\Users\zantan\ab_intraday')
FEAT_NAMES = ['chg5','chg10','chg20','chg60','d5','d10','d20','bull1','bull2',
              'rr','std20','vr','pos','nh','vpc','c1d','c3d','ex5','ex10','ex20',
              'skew20','kurt20','dn_streak','up_ratio10','vol_chg','kurt60',
              'slope5','slope10','accel','vp_shrink','vp_div']
TDX_FEATS = ['open30_ret','tail30_ret','vwap_dev','rv_1m','amp_intra',
             'vol_dist_am','vol_dist_tail','tail5_ret','last_vol_share']
COLS = FEAT_NAMES + TDX_FEATS

params = {
    'objective': 'regression', 'metric': 'l2',
    'num_leaves': 15, 'learning_rate': 0.008,
    'feature_fraction': 0.6, 'bagging_fraction': 0.6, 'bagging_freq': 5,
    'min_data_in_leaf': 300, 'lambda_l1': 0.5, 'lambda_l2': 2.0,
    'max_depth': 5, 'min_gain_to_split': 0.2, 'verbose': 1, 'num_threads': 8,
}

df = pd.read_parquet(BASE / 'ab_samples.parquet').sort_values('date').reset_index(drop=True)
dates = np.sort(df['date'].unique())
es_cut = dates[-10]                      # 最后10个交易日做早停集
fit_mask = (df['date'] < es_cut).to_numpy()
es_mask = ~fit_mask
print(f'样本 {len(df):,} 日截面 {len(dates)} fit {fit_mask.sum():,} es {es_mask.sum():,}')

X = df[COLS].to_numpy(dtype=np.float64).copy()
y = df['y'].to_numpy()
stats_list = []
for j, c in enumerate(COLS):
    v = X[fit_mask][:, j]; v = v[np.isfinite(v)]
    lo, hi = float(np.percentile(v, 1)), float(np.percentile(v, 99))
    mean, std = float(v.mean()), float(v.std())
    X[:, j] = (np.clip(X[:, j], lo, hi) - mean) / (std if std > 0 else 1.0)
    stats_list.append({'col': c, 'lo': lo, 'hi': hi, 'mean': mean, 'std': std})
X = np.nan_to_num(X)

d_fit = lgb.Dataset(X[fit_mask], y[fit_mask])
d_es = lgb.Dataset(X[es_mask], y[es_mask], reference=d_fit)
t0 = time.time()
m = lgb.train(params, d_fit, num_boost_round=2000, valid_sets=[d_es],
              valid_names=['es'], callbacks=[lgb.early_stopping(50), lgb.log_evaluation(100)])
m.save_model(str(BASE / 'model_B_final.txt'))
with open(BASE / 'stats_B.json', 'w') as f_:
    json.dump({'cols': COLS, 'stats': stats_list, 'trees': m.num_trees(),
               'trained_at': time.strftime('%Y-%m-%d %H:%M:%S'),
               'train_dates': f'{dates[0]}~{es_cut}', 'n_rows': int(fit_mask.sum())},
              f_, ensure_ascii=False, indent=1)
imp = sorted(zip(COLS, m.feature_importance('gain')), key=lambda x: -x[1])[:15]
print(f'FINAL_DONE trees={m.num_trees()} {time.time()-t0:.0f}s')
print('gain top15:', ', '.join(f'{c}:{v:.0f}' for c, v in imp))