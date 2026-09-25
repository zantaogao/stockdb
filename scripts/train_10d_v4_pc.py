"""10d v4 训练（PC 侧）— 输入 samples_v4.parquet，输出模型+norm stats+验证逐日IC
与 v3 的差异（方法学修正，参数完全照抄 v3）:
  1. 按日期切分(前80%日期训练/后20%验证)，修掉 v3 按行(按股票顺序)切的缺陷
  2. 标准化 mean/std/clip 只用训练段
  3. 验证集输出逐日截面 RankIC csv（供 Mac 配对检验/影子对跑）
参数照抄 train_10d_v3: num_leaves=15 lr=0.008 ff/bf=0.6 min_data=300 l1=0.5 l2=2.0
depth=5 min_gain=0.2, 2000轮 early_stop(50)
"""
import json, time
import numpy as np
import pandas as pd
import lightgbm as lgb
from scipy import stats
from pathlib import Path

import os
BASE = Path('C:/Users/zantan/retrain_10d_v4')
SAMPLES = os.environ.get('SAMPLES_FILE', 'samples_v4.parquet')
SUF = os.environ.get('OUT_SUFFIX', '')
df = pd.read_parquet(BASE / SAMPLES)
feats = [c for c in df.columns if c.startswith('f') and c != 'f']
feats = [f'f{j}' for j in range(31)]
print(f'样本: {len(df):,}  特征: {len(feats)}  日期: {df.date.min()} ~ {df.date.max()}', flush=True)

dates = np.sort(df['date'].unique())
split_date = dates[int(len(dates) * 0.8)]
tr = df[df['date'] < split_date]
va = df[df['date'] >= split_date]
print(f'切分日: {split_date}  训练 {len(tr):,} / 验证 {len(va):,}', flush=True)

# 标准化 stats 只用训练段
Xtr = tr[feats].to_numpy(dtype=float).copy()
Xva = va[feats].to_numpy(dtype=float).copy()
ytr = tr['y'].to_numpy(dtype=float)
yva = va['y'].to_numpy(dtype=float)
stats_dict = {}
for j, fname in enumerate(feats):
    v = Xtr[:, j]; v = v[np.isfinite(v)]
    lo, hi = np.percentile(v, 1), np.percentile(v, 99)
    mu, sd = float(v.mean()), float(v.std())
    stats_dict[f'feat_{j}'] = {'mean': mu, 'std': sd, 'low': float(lo), 'high': float(hi)}
    Xtr[:, j] = np.clip(Xtr[:, j], lo, hi); Xtr[:, j] = (Xtr[:, j] - mu) / sd
    Xva[:, j] = np.clip(Xva[:, j], lo, hi); Xva[:, j] = (Xva[:, j] - mu) / sd
Xtr = np.nan_to_num(Xtr, nan=0.0); Xva = np.nan_to_num(Xva, nan=0.0)

params = {
    'objective': 'regression', 'metric': 'l2',
    'num_leaves': 15, 'learning_rate': float(os.environ.get('LR_OVERRIDE', '0.008')),
    'feature_fraction': 0.6, 'bagging_fraction': 0.6, 'bagging_freq': 5,
    'min_data_in_leaf': 300, 'lambda_l1': 0.5, 'lambda_l2': 2.0,
    'max_depth': 5, 'min_gain_to_split': 0.2,
    'verbose': 1, 'num_threads': 8,
}
dtrain = lgb.Dataset(Xtr, ytr)
dval = lgb.Dataset(Xva, yva, reference=dtrain)
t0 = time.time()
model = lgb.train(params, dtrain, num_boost_round=2000,
                  valid_sets=[dtrain, dval], valid_names=['train', 'val'],
                  callbacks=[lgb.early_stopping(50), lgb.log_evaluation(200)])
print(f'训练耗时 {time.time()-t0:.0f}s  树数 {model.num_trees()}', flush=True)

pred = model.predict(Xva)
# 逐日截面 RankIC
va_dates = va['date'].to_numpy()
recs = []
for d in np.unique(va_dates):
    m = va_dates == d
    if m.sum() >= 200:
        ic = stats.spearmanr(pred[m], yva[m])[0]
        recs.append({'date': str(d), 'n': int(m.sum()), 'rank_ic': float(ic)})
pd.DataFrame(recs).to_csv(BASE / f'daily_ic_v4{SUF}.csv', index=False)
ics = [r['rank_ic'] for r in recs]
print(f'验证日均IC: {np.mean(ics):+.4f} (n={len(ics)}天)  正IC占比: {np.mean([i>0 for i in ics])*100:.0f}%', flush=True)

# 十分组
pairs = sorted(zip(pred, yva), key=lambda x: x[0])
d10 = max(1, len(pairs) // 10)
print('十分组:', ' '.join(f"D{d+1}:{np.mean([r for _,r in pairs[d*d10:(d+1)*d10 if d<9 else len(pairs)]])*100:+.2f}%" for d in range(10)), flush=True)

imp = model.feature_importance(importance_type='gain')
top = np.argsort(imp)[-15:][::-1]
json.dump({feats[j]: float(imp[j]) for j in top}, open(BASE / f'gain_top15_v4{SUF}.json', 'w'), indent=1)
model.save_model(str(BASE / f'lgb_reg_10d_v4{SUF}.txt'))
json.dump(stats_dict, open(BASE / f'v10_v4_stats{SUF}.json', 'w'))
report = {
    'trained_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    'samples_file': SAMPLES,
    'n_samples': int(len(df)), 'n_features': len(feats),
    'date_range': [str(df.date.min()), str(df.date.max())],
    'split_date': str(split_date), 'n_train': int(len(tr)), 'n_val': int(len(va)),
    'params': params, 'num_boost_round_max': 2000, 'early_stopping': 50,
    'best_iteration': int(model.best_iteration), 'num_trees': int(model.num_trees()),
    'val_daily_rank_ic_mean': float(np.mean(ics)), 'val_days': len(ics),
    'pos_ic_ratio': float(np.mean([i > 0 for i in ics])),
    'daily_ic_csv': str(BASE / f'daily_ic_v4{SUF}.csv'),
    'deciles_pct': [float(np.mean([r for _, r in pairs[d*d10:(d+1)*d10 if d < 9 else len(pairs)]]) * 100) for d in range(10)],
    'gain_top15': str(BASE / f'gain_top15_v4{SUF}.json'),
}
json.dump(report, open(BASE / f'train_10d_v4_results{SUF}.json', 'w'), indent=1, ensure_ascii=False)
print('SAVED: lgb_reg_10d_v4.txt + v10_v4_stats.json + daily_ic_v4.csv + gain_top15_v4.json + train_10d_v4_results.json')