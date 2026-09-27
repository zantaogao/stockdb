"""三模型重训·PC 侧训练 v3（2026-09-26）
输入: samples_10d.parquet (date, code, f0..f30, y10)
      samples_20d.parquet (date, code, f0..f30, y20)
方法学 = train_10d_v4_pc.py 的 v3 参数 + 两处修正（按日期80/20切分、标准化只用训练段统计）:
  num_leaves=15 lr=0.008 ff/bf=0.6 min_data=300 l1=0.5 l2=2.0 depth=5 min_gain=0.2
  2000轮 early_stop(50)
输出: lgb_reg_10d_v5.txt v10_v5_stats.json daily_ic_10d_v5.csv train_10d_v5_results.json
      lgb_reg_20d_v2.txt v20_v2_stats.json daily_ic_20d_v2.csv train_20d_v2_results.json
"""
import json, time, os
import numpy as np
import pandas as pd
import lightgbm as lgb
from scipy import stats
from pathlib import Path

BASE = Path(os.environ.get('RETRAIN_DIR', 'C:/Users/zantan/retrain_20260926'))
os.makedirs(BASE / 'out', exist_ok=True)
params = {
    'objective': 'regression', 'metric': 'l2',
    'num_leaves': 15, 'learning_rate': 0.008,
    'feature_fraction': 0.6, 'bagging_fraction': 0.6, 'bagging_freq': 5,
    'min_data_in_leaf': 300, 'lambda_l1': 0.5, 'lambda_l2': 2.0,
    'max_depth': 5, 'min_gain_to_split': 0.2,
    'verbose': 1, 'num_threads': 8,
}

def _outp(name):
    return BASE / 'out' / name

def train_one(tag, parquet, ycol, feats_n, model_name, stats_name, ic_name, params_, feat_cols=None):
    df = pd.read_parquet(BASE / parquet)
    df['date'] = df['date'].astype(str).str.replace('-', '', regex=False)
    feats = feat_cols or [f'f{j}' for j in range(feats_n)]
    print(f'[{tag}] 样本 {len(df):,} 特征 {len(feats)} 范围 {df.date.min()}~{df.date.max()}', flush=True)
    dates = np.sort(df['date'].unique())
    split_date = dates[int(len(dates) * 0.8)]
    tr = df[df['date'] < split_date]; va = df[df['date'] >= split_date]
    print(f'[{tag}] 切分日 {split_date}  训练 {len(tr):,}  验证 {len(va):,}', flush=True)

    Xtr = tr[feats].to_numpy(dtype=float).copy()
    Xva = va[feats].to_numpy(dtype=float).copy()
    ytr = tr[ycol].to_numpy(dtype=float); yva = va[ycol].to_numpy(dtype=float)
    stats_dict = {}
    for j, fname in enumerate(feats):
        v = Xtr[:, j]; v = v[np.isfinite(v)]
        lo, hi = np.percentile(v, 1), np.percentile(v, 99)
        mu, sd = float(v.mean()), float(v.std())
        stats_dict[f'feat_{j}'] = {'mean': mu, 'std': sd, 'low': float(lo), 'high': float(hi)}
        Xtr[:, j] = (np.clip(Xtr[:, j], lo, hi) - mu) / sd
        Xva[:, j] = (np.clip(Xva[:, j], lo, hi) - mu) / sd
    Xtr = np.nan_to_num(Xtr, nan=0.0); Xva = np.nan_to_num(Xva, nan=0.0)

    dtrain = lgb.Dataset(Xtr, ytr); dval = lgb.Dataset(Xva, yva, reference=dtrain)
    t0 = time.time()
    round_ = params_.pop('_max_rounds', 2000)
    model = lgb.train(params_, dtrain, num_boost_round=round_,
                      valid_sets=[dtrain, dval], valid_names=['train', 'val'],
                      callbacks=[lgb.early_stopping(params_.pop('_es', 50)), lgb.log_evaluation(200)])
    print(f'[{tag}] 训练耗时 {time.time()-t0:.0f}s  树数 {model.num_trees()}  best_iter {model.best_iteration}', flush=True)

    pred = model.predict(Xva)
    va_dates = va['date'].to_numpy()
    recs = []
    for d in np.unique(va_dates):
        m = va_dates == d
        if m.sum() >= 200:
            ic = stats.spearmanr(pred[m], yva[m])[0]
            recs.append({'date': str(d), 'n': int(m.sum()), 'rank_ic': float(ic)})
    pd.DataFrame(recs).to_csv(_outp(ic_name), index=False)
    ics = [r['rank_ic'] for r in recs]
    print(f'[{tag}] 验证日均IC {np.mean(ics):+.4f} (n={len(ics)}天)  正IC占比 {np.mean([i>0 for i in ics])*100:.0f}%', flush=True)

    pairs = sorted(zip(pred, yva), key=lambda x: x[0])
    d10 = max(1, len(pairs) // 10)
    deciles = []
    for dd in range(10):
        chunk = pairs[dd*d10:(dd+1)*d10] if dd < 9 else pairs[9*d10:]
        deciles.append(float(np.mean([r for _, r in chunk]) * 100))
    print(f'[{tag}] 十分组:', ' '.join(f'D{i+1}:{v:+.2f}%' for i, v in enumerate(deciles)), flush=True)

    model.save_model(str(_outp(model_name)))
    json.dump(stats_dict, open(_outp(stats_name), 'w'))
    json.dump({
        'trained_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'samples_file': parquet,
        'n_samples': int(len(df)), 'n_features': len(feats),
        'date_range': [str(df.date.min()), str(df.date.max())],
        'split_date': str(split_date), 'n_train': int(len(tr)), 'n_val': int(len(va)),
        'params': {k: v for k, v in params_.items() if not k.startswith('_')}, 'num_boost_round_max': round_, 'best_iteration': int(model.best_iteration), 'num_trees': int(model.num_trees()),
        'val_daily_rank_ic_mean': float(np.mean(ics)), 'val_days': len(ics),
        'pos_ic_ratio': float(np.mean([i > 0 for i in ics])), 'deciles_pct': deciles,
    }, open(_outp(f'train_{tag}_results.json'), 'w'), indent=1, ensure_ascii=False)
    print(f'[{tag}] SAVED {model_name}', flush=True)

params_20 = dict(params); params_20.update({'num_leaves': 31, 'learning_rate': 0.01, 'feature_fraction': 0.7, 'bagging_fraction': 0.7, 'min_data_in_leaf': 200, 'lambda_l1': 0.1, 'lambda_l2': 1.0, 'max_depth': 6, 'min_gain_to_split': 0.0}); params_20['_max_rounds'] = 5000; params_20['_es'] = 100
only = os.environ.get('RETRAIN_ONLY', 'both')
if only in ('both', '10d'):
    train_one('10d_v6', 'samples_10d_v6.parquet', 'y10', 31, 'lgb_reg_10d_v6.txt', 'v10_v6_stats.json', 'daily_ic_10d_v6.csv', dict(params, _max_rounds=2000, _es=50))
if only in ('both', '20d'):
    train_one('20d_v2', 'samples_20d.parquet', 'y20', 31, 'lgb_reg_20d_v2.txt', 'v20_v2_stats.json', 'daily_ic_20d_v2.csv', params_20)
print('ALL_DONE', flush=True)
