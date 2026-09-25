#!/usr/bin/env python3
"""
40d训练脚本 - 上传到PC并在PC上执行
- 读取前复权 stock.db
- compute_feats 计算特征
- LightGBM GPU 训练40d回归模型
- 保存模型 + norm_stats
"""
import sys, os, json

sys.path.insert(0, r"C:\Users\pumma\factor_lib")
os.chdir(r"C:\Users\pumma\factor_lib")

import lightgbm as lgb
print(f"LightGBM: {lgb.__version__}")

import duckdb
con = duckdb.connect(r"C:\Users\pumma\factor_lib\stock.db", read_only=True)
df = con.execute("SELECT * FROM stock_daily WHERE turn_rate > 0 AND close > 0").fetchdf()
con.close()
print(f"Data: {len(df)} rows total")

from core.features import compute_feats
feat_df = compute_feats(df)
print(f"Features: {feat_df.shape}")

feat_cols = [c for c in feat_df.columns if c.startswith(('ex', 'd_')) and c != 'ex5_days']
target_col = 'chg_40d'
print(f"Using {len(feat_cols)} features")

train = feat_df[(feat_df['date'] >= '2020-01-01') & (feat_df['date'] < '2025-03-01')]
val = feat_df[(feat_df['date'] >= '2025-03-01') & (feat_df['date'] < '2025-10-01')]
test = feat_df[feat_df['date'] >= '2025-10-01']

train = train.dropna(subset=[target_col] + feat_cols, how='any')
val = val.dropna(subset=[target_col] + feat_cols, how='any')
test = test.dropna(subset=[target_col] + feat_cols, how='any')
print(f"Train:{len(train)} Val:{len(val)} Test:{len(test)}")

norm_stats = {}
for c in feat_cols:
    col_data = train[c].dropna()
    norm_stats[c] = [float(col_data.mean()), float(col_data.std())]

for c in feat_cols:
    m, s = norm_stats[c]
    train[c] = (train[c] - m) / s if s > 0 else 0.0
    val[c] = (val[c] - m) / s if s > 0 else 0.0
    test[c] = (test[c] - m) / s if s > 0 else 0.0

params = {
    'objective': 'regression', 'metric': 'mae',
    'boosting_type': 'gbdt', 'num_leaves': 63,
    'learning_rate': 0.015, 'feature_fraction': 0.7,
    'bagging_fraction': 0.8, 'bagging_freq': 5,
    'min_child_samples': 100, 'verbosity': -1,
    'num_threads': 24, 'device': 'gpu',
    'gpu_device_id': 0, 'gpu_use_dp': False
}

train_data = lgb.Dataset(train[feat_cols], label=train[target_col])
val_data = lgb.Dataset(val[feat_cols], label=val[target_col])

model = lgb.train(
    params, train_data,
    valid_sets=[val_data],
    num_boost_round=2000,
    callbacks=[lgb.early_stopping(50), lgb.log_evaluation(100)]
)
print(f"Best iter: {model.best_iteration}, Best MAE: {model.best_score['valid_0']['l1']:.4f}")

model.save_model(r"C:\Users\pumma\factor_lib\lgb_reg_40d_v6plus.txt")
with open(r"C:\Users\pumma\factor_lib\v6_norm_stats_40d.json", 'w') as f:
    json.dump(norm_stats, f, indent=2)
print("Model and norm_stats saved OK")

preds = model.predict(test[feat_cols])
test_df = test.copy()
test_df['pred'] = preds
from scipy.stats import spearmanr
ic, _ = spearmanr(test_df['pred'], test_df[target_col])
print(f"Test IC: {ic:.4f}")

test_df['pred_rank'] = test_df['pred'].rank(pct=True)
top = test_df[test_df['pred_rank'] > 0.9]
bot = test_df[test_df['pred_rank'] < 0.1]
spread = top[target_col].mean() - bot[target_col].mean()
print(f"Top10% mean: {top[target_col].mean():.4f}")
print(f"Bot10% mean: {bot[target_col].mean():.4f}")
print(f"Spread: {spread:.4f}")
print("=== DONE ===")
