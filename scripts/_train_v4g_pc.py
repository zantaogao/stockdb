# -*- coding: utf-8 -*-
"""v4g 终审（2026-09-20）：v4f(38维) vs v4f+1分钟6维(44维)
样本 = v4d_retrain/samples_v4c.parquet + _uncon_feats.parquet + v4f_retrain/micro_feats_0919.parquet
新维 = v4g_retrain/min1_feats_0920.parquet（gap_ret/tail5_ret/last_vol_share/vd_t30/vd_m2/ovr20，2026-02-12起）
方法学照抄 v4f 轮：截断到新维窗口内按日期切 80/20、31维护训练段 stats、31+ 维不标准化 NaN 直喂、
两臂同轮数（早停在短窗不可用）、NW-t lag10、分月拆解、pair=0 断言、训练段覆盖率断言。
"""
import json, time, sys
import numpy as np, pandas as pd, lightgbm as lgb
from scipy import stats
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = 'C:/Users/zantan/v4g_retrain'
t0 = time.time()
sm = pd.read_parquet('C:/Users/zantan/v4d_retrain/samples_v4c.parquet')
uf = pd.read_parquet('C:/Users/zantan/v4d_retrain/_uncon_feats.parquet')
sm = sm.merge(uf.rename(columns={'symbol': 'code'}), on=['code', 'date'], how='left')
mf = pd.read_parquet('C:/Users/zantan/v4f_retrain/micro_feats_0919.parquet')
mf['code'] = mf['ts_code'].str.split('.').str[-1].str.zfill(6)
mf['date'] = pd.to_datetime(mf['trade_date'], format='%Y%m%d').dt.strftime('%Y-%m-%d')
mf = mf[['code', 'date', 'kyle', 'amihud']].drop_duplicates(['code', 'date'])
sm = sm.merge(mf, on=['code', 'date'], how='left')
m1 = pd.read_parquet(BASE + '/min1_feats_0920.parquet')
MIN6 = ['gap_ret','tail5_ret','last_vol_share','vd_t30','vd_m2','ovr20']
# 盖帽防爆表：ovr20/gap_ret 有复牌怪值，按全池 p0.5/p99.5 clip（保留 NaN）
for f in ['gap_ret','ovr20']:
    lo, hi = m1[f].quantile(0.005), m1[f].quantile(0.995)
    m1[f] = m1[f].clip(lo, hi)
m1 = m1[['code','date'] + MIN6].drop_duplicates(['code','date'])
n0 = len(sm)
sm = sm.merge(m1, on=['code', 'date'], how='left')
assert len(sm) == n0, f'merge 改变行数 {n0}->{len(sm)}'
feats31 = [f'f{j}' for j in range(31)]
NEW5 = ['f39_vol_diverge', 'f32_zha20', 'f34_overnight_share', 'f43_turn_cv20', 'f44_skew20']
NEW2 = ['kyle', 'amihud']
feats = feats31 + NEW5 + NEW2 + MIN6
# 截断到 1 分钟窗口
sm = sm[sm['date'] >= '2026-02-12'].reset_index(drop=True)
print(f'截断到 1 分钟窗口 {len(sm):,} 行', flush=True)

dates = np.sort(sm['date'].unique()); split = dates[int(len(dates) * 0.8)]
tr = sm[sm['date'] < split]; va = sm[sm['date'] >= split]
print(f'切分日 {split} 训练 {len(tr):,} / 验证 {len(va):,}  训练段gap覆盖率 {100*tr["gap_ret"].notna().mean():.1f}%', flush=True)
assert tr['gap_ret'].notna().mean() > 0.5

Xtr = tr[feats].to_numpy(dtype=float).copy(); Xva = va[feats].to_numpy(dtype=float).copy()
ytr = tr['y'].to_numpy(dtype=float); yva = va['y'].to_numpy(dtype=float)
stats_dict = {}
for j in range(31):
    v = Xtr[:, j]; v = v[np.isfinite(v)]
    lo, hi = np.percentile(v, 1), np.percentile(v, 99)
    mu, sd = float(v.mean()), float(v.std())
    stats_dict[feats[j]] = {'mean': mu, 'std': sd, 'low': float(lo), 'high': float(hi)}
    Xtr[:, j] = (np.clip(Xtr[:, j], lo, hi) - mu) / sd
    Xva[:, j] = (np.clip(Xva[:, j], lo, hi) - mu) / sd
Xtr[:, 31:] = np.where(np.isfinite(Xtr[:, 31:]), Xtr[:, 31:], np.nan)
Xva[:, 31:] = np.where(np.isfinite(Xva[:, 31:]), Xva[:, 31:], np.nan)
for j in range(36, 44):
    v = Xtr[:, j]; v = v[np.isfinite(v)]
    stats_dict[feats[j]] = {'mean': float(v.mean()), 'std': float(v.std()),
                            'low': float(np.percentile(v, 1)), 'high': float(np.percentile(v, 99))}

params = {'objective': 'regression', 'metric': 'l2', 'num_leaves': 15, 'learning_rate': 0.008,
 'feature_fraction': 0.6, 'bagging_fraction': 0.6, 'bagging_freq': 5, 'min_data_in_leaf': 300,
 'lambda_l1': 0.5, 'lambda_l2': 2.0, 'max_depth': 5, 'min_gain_to_split': 0.2, 'verbose': 1, 'num_threads': 8}
ROUNDS = 300  # ~100 训练日的短窗定死轮数（0.008 lr 下约等于 v4d 620 棵在 280 日窗的学习量），两臂同
model = lgb.train(params, lgb.Dataset(Xtr, ytr), num_boost_round=ROUNDS,
  valid_sets=[lgb.Dataset(Xtr, ytr), lgb.Dataset(Xva, yva)], valid_names=['train', 'val'],
  callbacks=[lgb.log_evaluation(100)])
pred = model.predict(Xva)
vd = va['date'].to_numpy()
def daily_ic(p):
    out = {}
    for dte in np.unique(vd):
        m = vd == dte
        if m.sum() >= 200: out[str(dte)] = float(stats.spearmanr(p[m], yva[m])[0])
    return pd.Series(out)
ic_a = daily_ic(pred); ic_a.to_csv(BASE + '/daily_ic_v4g.csv')
print(f'v4g(44维) IC {ic_a.mean():+.4f} (n={len(ic_a)}) 正占比 {(ic_a > 0).mean()*100:.0f}% 用时{time.time()-t0:.0f}s', flush=True)

m38 = lgb.train(params, lgb.Dataset(Xtr[:, :38], ytr), num_boost_round=ROUNDS)
pred_b = m38.predict(Xva[:, :38])
ic_b = daily_ic(pred_b); ic_b.to_csv(BASE + '/daily_ic_v4g_base38.csv')
print(f'base38(=v4f) IC {ic_b.mean():+.4f}', flush=True)
assert float(np.abs(pred - pred_b).max()) > 0, 'A/B 预测完全相同 = 新维没吃进，本轮作废'

j = pd.concat([ic_a, ic_b], axis=1, keys=['a', 'b']).dropna()
dd = (j['a'] - j['b']).to_numpy(); n = len(dd); mu = dd.mean(); x = dd - mu; l = 10
gw = ((x * x).sum() + sum(2 * (1 - i / (l + 1)) * (x[i:] * x[:-i]).sum() for i in range(1, l + 1))) / n
se = np.sqrt(gw / n)
print(f'配对差 {mu:+.5f} NW-t {mu/se:+.2f} (n={n})', flush=True)
mm = j.copy(); mm.index = pd.to_datetime(mm.index)
mo = mm.groupby(mm.index.to_period('M')).apply(lambda s: float((s['a'] - s['b']).mean()))
print('分月配对差:', {str(k): round(v, 4) for k, v in mo.items()}, flush=True)

imp = model.feature_importance(importance_type='gain')
top = sorted(zip(feats, imp), key=lambda t: -t[1])[:15]
print('gain top15:', ' '.join(f'{k}:{v/1e3:.0f}k' for k, v in top), flush=True)
gi = dict(zip(feats, imp.astype(float)))
print(' '.join(f'{f} gain {gi[f]/1e3:.0f}k' for f in MIN6), flush=True)
pairs = sorted(zip(pred, yva), key=lambda t: t[0]); d10 = max(1, len(pairs) // 10)
dec = [float(np.mean([r for _, r in pairs[k*d10:(k+1)*d10]]) * 100) for k in range(10)]
print('十分组:', ' '.join(f'D{k+1}:{v:+.2f}%' for k, v in enumerate(dec)), flush=True)
model.save_model(BASE + '/lgb_reg_v4g.txt')
json.dump(stats_dict, open(BASE + '/stats_v4g.json', 'w'))
json.dump({'split_date': str(split), 'rounds': ROUNDS,
 'ic_v4g': float(ic_a.mean()), 'ic_base38': float(ic_b.mean()), 'pair_nw_t': float(mu / se),
 'pair_mean_diff': float(mu), 'val_days': int(n), 'pos_ratio_v4g': float((ic_a > 0).mean()),
 'monthly_diff': {str(k): v for k, v in mo.items()},
 'gains_min6': {f: gi[f] for f in MIN6},
 'gain_top15': {k: float(v) for k, v in top}, 'deciles': dec},
 open(BASE + '/train_v4g_results.json', 'w'), indent=1)
print(f'完成 {time.time()-t0:.0f}s', flush=True)
