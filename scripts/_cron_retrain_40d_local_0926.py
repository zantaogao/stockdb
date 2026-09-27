"""40d 增量训练（2026-09-26 重训·本地版）
输入: samples_40d.parquet (date, code, f0..f25=BASE_KEEP26, f31..f33=因子3维, y40)
      —— 特征已按生产口径算好（feat_tushare + stk_factor），本脚本只做训练+对拍。
方法 = scripts/train_40d_incremental.py 原样:
  params: lr=0.01 leaves=15 ff/bf=0.7 depth=5 l1=0.3 l2=2.0 min_data=20 round=400 early_stop=30 (2000轮上限、50早停未在此脚本=400/30)
  1% winsorize + z-score（全量统计，原脚本如此）
  与旧模型对拍: 新树数 <= 旧树数*1.15 且 Spearman>=0.95 才收，否则 block
输出: lgb_reg_40d_inc_v2.txt + train_40d_inc_results.json
"""
import json, time, sys
import numpy as np
import pandas as pd
import lightgbm as lgb
from pathlib import Path
from scipy import stats

BASE = Path.home() / '.hermes/stockdb'
MODELS = BASE / 'models'
OUT = BASE / 'analysis/retrain_20260926'

OLD_MODEL = MODELS / 'retired_20260926/lgb_reg_40d_new_stkfactor.txt'
NORM = MODELS / 'retired_20260926/v6_norm_stats_40d_tushare_v2_stkfactor.json'
FWD = 40
params = {'objective':'regression','metric':'l2','num_leaves':15,'learning_rate':0.01,
          'feature_fraction':0.7,'bagging_fraction':0.7,'bagging_freq':5,
          'min_data_in_leaf':20,'lambda_l1':0.3,'lambda_l2':2.0,
          'max_depth':5,'verbose':1,'num_threads':8}

df = pd.read_parquet(OUT / 'samples_40d.parquet')
feats = ['f%d'%j for j in range(26)] + ['f31','f32','f33']
print(f'增量样本 {len(df):,} 特征 {len(feats)} 范围 {df.date.min()}~{df.date.max()}', flush=True)
X = df[feats].to_numpy(dtype=float); y = df['y40'].to_numpy(dtype=float)

norm = json.load(open(NORM))
for j in range(len(feats)):
    k = f'feat_{j}'
    lo, hi, mu, sd = norm[k]['low'], norm[k]['high'], norm[k]['mean'], norm[k]['std']
    X[:, j] = (np.clip(X[:, j], lo, hi) - mu) / sd
X = np.nan_to_num(X, nan=0.0)

old = lgb.Booster(model_file=str(OLD_MODEL))
old_trees = old.num_trees()
old_pred = old.predict(X)

dtrain = lgb.Dataset(X, y)
t0 = time.time()
new = lgb.train(params, dtrain, valid_sets=[dtrain],
                init_model=str(OLD_MODEL), num_boost_round=400,
                callbacks=[lgb.early_stopping(30), lgb.log_evaluation(100)])
print(f'训练耗时 {time.time()-t0:.0f}s  旧树 {old_trees}  新树 {new.num_trees()}', flush=True)

# 对拍
pred = new.predict(X)
rho = stats.spearmanr(old_pred, pred).correlation
tree_ok = new.num_trees() <= old_trees * 1.15
print(f'新旧 Spearman {rho:.4f}  树数增长 {new.num_trees()/old_trees:.2f}x', flush=True)

last_dates = sorted(df.date.unique())[-120:]
test_mask = df.date.isin(last_dates).to_numpy()
ics = []
for d in last_dates:
    m = (df.date == d).to_numpy()
    if m.sum() >= 500:
        ics.append(stats.spearmanr(pred[m], y[m]).correlation)
print(f'增量末段日IC均值: {np.mean(ics):.4f} (n={len(ics)})', flush=True)

result = {'trained_at': time.strftime('%Y-%m-%d %H:%M:%S'),
          'n_samples': int(len(df)), 'date_range': [str(df.date.min()), str(df.date.max())],
          'old_trees': int(old_trees), 'new_trees': int(new.num_trees()),
          'spearman_old_new': float(rho), 'last120_daily_ic_mean': float(np.mean(ics)),
          'params': params, 'tree_growth_ok': bool(tree_ok), 'rho_ok': bool(rho >= 0.95)}
json.dump(result, open(OUT / 'train_40d_inc_results.json', 'w'), indent=1, ensure_ascii=False)

if tree_ok and rho >= 0.95:
    new.save_model(str(OUT / 'lgb_reg_40d_inc_v2.txt'))
    print(f'SAVED lgb_reg_40d_inc_v2.txt ({new.num_trees()} 树)', flush=True)
else:
    print(f'NOT SAVED: tree_ok={tree_ok} rho={rho:.4f} (<0.95 拒收，与旧模型信号重构)', flush=True)
