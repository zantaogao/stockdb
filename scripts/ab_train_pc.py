# -*- coding: utf-8 -*-
"""日内特征 A/B 对拍 — PC 端训练（ab_samples.parquet 由 Mac 拼好搬来）
A版=31基础特征 B版=31+9日内特征。同切分(前80%日期训练/后20%验证,按日期排)、
同参数、同标准化(train窗stats)。输出: 验证集逐日RankIC(csv回传Mac做配对t检验)、gain排名。
用法: python ab_train_pc.py
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
VAL_RATIO = 0.2  # 按日期切：最后20%交易日做验证

df = pd.read_parquet(BASE / 'ab_samples.parquet').sort_values('date').reset_index(drop=True)
dates = np.sort(df['date'].unique())
val_cut = dates[int(len(dates) * (1 - VAL_RATIO))]
tr_mask = df['date'] < val_cut
print(f'样本 {len(df):,} 日截面 {len(dates)} 验证切点 {val_cut} train {tr_mask.sum():,} val {(~tr_mask).sum():,}')

params = {
    'objective': 'regression', 'metric': 'l2',
    'num_leaves': 15, 'learning_rate': 0.008,
    'feature_fraction': 0.6, 'bagging_fraction': 0.6, 'bagging_freq': 5,
    'min_data_in_leaf': 300, 'lambda_l1': 0.5, 'lambda_l2': 2.0,
    'max_depth': 5, 'min_gain_to_split': 0.2, 'verbose': 1, 'num_threads': 8,
}

def run(name, cols):
    X = df[cols].to_numpy(dtype=np.float64).copy(); y = df['y'].to_numpy()
    # 标准化统计只用train窗
    for j, c in enumerate(cols):
        v = X[tr_mask.to_numpy()][:, j]
        v = v[np.isfinite(v)]
        lo, hi = np.percentile(v, 1), np.percentile(v, 99)
        X[:, j] = np.clip(X[:, j], lo, hi)
        X[:, j] = (X[:, j] - v.mean()) / (v.std() if v.std() > 0 else 1)
    X = np.nan_to_num(X)
    Xt, yt, Xv, yv = X[tr_mask.to_numpy()], y[tr_mask.to_numpy()], X[~tr_mask.to_numpy()], y[~tr_mask.to_numpy()]
    dt_ = lgb.Dataset(Xt, yt); dv = lgb.Dataset(Xv, yv, reference=dt_)
    t0 = time.time()
    m = lgb.train(params, dt_, num_boost_round=2000, valid_sets=[dv],
                  valid_names=['val'], callbacks=[lgb.early_stopping(50), lgb.log_evaluation(200)])
    pv = m.predict(Xv)
    vdf = df[~tr_mask].copy(); vdf['pred'] = pv
    daily = vdf.groupby('date').apply(
        lambda g: stats.spearmanr(g['pred'], g['y'])[0] if len(g) > 50 else np.nan,
        include_groups=False).dropna()
    mean_ic = daily.mean()
    t_stat = mean_ic / (daily.std(ddof=1) / np.sqrt(len(daily)))
    # 十分组
    pairs = sorted(zip(pv, yv), key=lambda x: x[0])
    d10 = max(1, len(pairs) // 10)
    top_ret = np.mean([r for _, r in pairs[-d10:]]) * 100
    bot_ret = np.mean([r for _, r in pairs[:d10]]) * 100
    imp = sorted(zip(cols, m.feature_importance('gain')), key=lambda x: -x[1])[:15]
    print(f'== {name}: 树{m.num_trees()} val日均IC {mean_ic:+.4f} t={t_stat:+.2f} '
          f'D10 {top_ret:+.2f}% D1 {bot_ret:+.2f}% spread {top_ret-bot_ret:+.2f}% ({time.time()-t0:.0f}s)')
    print('   gain top15:', ', '.join(f'{c}:{v:.0f}' for c, v in imp))
    daily.rename('ic').to_csv(BASE / f'daily_ic_{name}.csv', header=True)
    m.save_model(str(BASE / f'model_{name}.txt'))
    return {'mean_ic': mean_ic, 't': t_stat, 'trees': m.num_trees(),
            'd10': top_ret, 'd1': bot_ret,
            'gain_top15': [[c, float(v)] for c, v in imp]}

res = {}
res['A'] = run('A_base', FEAT_NAMES)
res['B'] = run('B_intraday', FEAT_NAMES + TDX_FEATS)
with open(BASE / 'ab_results.json', 'w') as f:
    json.dump(res, f, ensure_ascii=False, indent=1)
print('DONE')