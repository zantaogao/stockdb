# -*- coding: utf-8 -*-
"""滚动窗 A/B 验证（PC 端）：expanding 训练窗 + 6 折×15 交易日验证 = 90 个验证日
每折：训练=验证折起点之前的全部样本（内部拿训练段最后10天做早停集，测试折不碰）；
标准化stats只用训练段；A/B 同训练样本、同折、同参数。
输出 daily_ic_roll_A.csv / daily_ic_roll_B.csv（date,fold,ic）+ roll_results.json
"""
import json, time
import numpy as np, pandas as pd
import lightgbm as lgb
from scipy import stats
from pathlib import Path

BASE = Path(r'C:\Users\zantan\ab_intraday')
FEAT_NAMES = ['chg5','chg10','chg20','chg60','d5','d10','d20','bull1','bull2',
              'rr','std20','vr','pos','nh','vpc','c1d','c3d','ex5','ex10','ex20',
              'skew20','kurt20','dn_streak','up_ratio10','vol_chg','kurt60',
              'slope5','slope10','accel','vp_shrink','vp_div']
TDX_FEATS = ['open30_ret','tail30_ret','vwap_dev','rv_1m','amp_intra',
             'vol_dist_am','vol_dist_tail','tail5_ret','last_vol_share']
MIN_TRAIN_DAYS, FOLD, N_FOLDS = 30, 15, 6

params = {
    'objective': 'regression', 'metric': 'l2',
    'num_leaves': 15, 'learning_rate': 0.008,
    'feature_fraction': 0.6, 'bagging_fraction': 0.6, 'bagging_freq': 5,
    'min_data_in_leaf': 300, 'lambda_l1': 0.5, 'lambda_l2': 2.0,
    'max_depth': 5, 'min_gain_to_split': 0.2, 'verbose': 1, 'num_threads': 8,
}

df = pd.read_parquet(BASE / 'ab_samples.parquet').sort_values('date').reset_index(drop=True)
dates = np.sort(df['date'].unique())
assert len(dates) >= MIN_TRAIN_DAYS + N_FOLDS * FOLD, f'样本日数{len(dates)}不够'
print(f'样本 {len(df):,} 行, {len(dates)} 个日截面 {dates[0]}~{dates[-1]}')

def daily_ic(vdf, pred):
    out = {}
    vdf = vdf.assign(pred=pred)
    for dt, g in vdf.groupby('date'):
        if len(g) > 50:
            ic = stats.spearmanr(g['pred'], g['y'])[0]
            if np.isfinite(ic):
                out[dt] = ic
    return out

recs = {'A': [], 'B': []}
fold_info = []
for k in range(N_FOLDS):
    val_dates = dates[MIN_TRAIN_DAYS + k*FOLD : MIN_TRAIN_DAYS + (k+1)*FOLD]
    v_first, v_last = val_dates[0], val_dates[-1]
    tr_mask = (df['date'] < v_first).to_numpy()
    es_cut = dates[MIN_TRAIN_DAYS + k*FOLD - 10]  # 训练段最后10天做早停集
    fit_mask = tr_mask & (df['date'] < es_cut).to_numpy()
    es_mask = tr_mask & ~fit_mask
    info = {'fold': k, 'val': f'{v_first}~{v_last}', 'train_rows': int(tr_mask.sum())}
    res = {}
    for name, cols in (('A', FEAT_NAMES), ('B', FEAT_NAMES + TDX_FEATS)):
        t0 = time.time()
        X = df[cols].to_numpy(dtype=np.float64).copy()
        y = df['y'].to_numpy()
        for j in range(X.shape[1]):  # 标准化：只用fit段stats
            v = X[fit_mask][:, j]; v = v[np.isfinite(v)]
            lo, hi = np.percentile(v, 1), np.percentile(v, 99)
            X[:, j] = (np.clip(X[:, j], lo, hi) - v.mean()) / (v.std() if v.std() > 0 else 1)
        X = np.nan_to_num(X)
        d_fit = lgb.Dataset(X[fit_mask], y[fit_mask])
        d_es = lgb.Dataset(X[es_mask], y[es_mask], reference=d_fit)
        m = lgb.train(params, d_fit, num_boost_round=2000, valid_sets=[d_es],
                      valid_names=['es'], callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)])
        vm = tr_mask.__invert__() & df['date'].isin(val_dates).to_numpy()
        ics = daily_ic(df[vm], m.predict(X[vm]))
        recs[name].extend({'date': d_, 'fold': k, 'ic': ic} for d_, ic in ics.items())
        info[name] = {'trees': m.num_trees(), 'days': len(ics),
                      'mean_ic': round(float(np.mean(list(ics.values()))), 4), 's': round(time.time()-t0)}
    info['B-A'] = round(info['B']['mean_ic'] - info['A']['mean_ic'], 4)
    fold_info.append(info)
    print(f"fold{k} val {v_first}~{v_last} A {info['A']['mean_ic']:+.4f} "
          f"B {info['B']['mean_ic']:+.4f} B-A {info['B-A']:+.4f} ({info['A']['s']}s/{info['B']['s']}s)", flush=True)

pd.DataFrame(recs['A']).to_csv(BASE / 'daily_ic_roll_A.csv', index=False)
pd.DataFrame(recs['B']).to_csv(BASE / 'daily_ic_roll_B.csv', index=False)
with open(BASE / 'roll_results.json', 'w') as f_:
    json.dump(fold_info, f_, ensure_ascii=False, indent=1)
print('ROLL_DONE')