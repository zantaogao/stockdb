# -*- coding: utf-8 -*-
"""v4h 模型端实验（2026-09-20）：同一份 38 维样本，四条链路比 IC
背景：v4d/v4f 用 L2 回归拟合原始 fwd10——y 重尾（max +565%），L2 把树力全砸在极少数爆拉股上，
而评估口径是截面排序（IC）。损失-目标错配是模型端第一个该动的地方。
臂 A: base36 L2（复现 v4d，620 棵，锚）
臂 B: 38维 L2（复现 v4f，620 棵）
臂 C: 38维 L2 + 标签改逐日截面 rank 分位（去掉重尾，损失≈排序）
臂 D: 38维 LambdaRank（ndcg@100，逐日 query 分组，graded relevance 10 档）
同一切分（截断 2025-04-08 后按日期 80/20）、同一验证段、同一评估（逐日 Spearman(pred, 原始y)）、配对 NW-t lag10。
"""
import json, time, sys
import numpy as np, pandas as pd, lightgbm as lgb
from scipy import stats
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = 'C:/Users/zantan/v4h_retrain'
t0 = time.time()
sm = pd.read_parquet('C:/Users/zantan/v4d_retrain/samples_v4c.parquet')
uf = pd.read_parquet('C:/Users/zantan/v4d_retrain/_uncon_feats.parquet')
sm = sm.merge(uf.rename(columns={'symbol': 'code'}), on=['code', 'date'], how='left')
mf = pd.read_parquet('C:/Users/zantan/v4f_retrain/micro_feats_0919.parquet')
mf['code'] = mf['ts_code'].str.split('.').str[-1].str.zfill(6)
mf['date'] = pd.to_datetime(mf['trade_date'], format='%Y%m%d').dt.strftime('%Y-%m-%d')
mf = mf[['code', 'date', 'kyle', 'amihud']].drop_duplicates(['code', 'date'])
n0 = len(sm)
sm = sm.merge(mf, on=['code', 'date'], how='left')
assert len(sm) == n0
sm = sm[sm['date'] >= '2025-04-08'].reset_index(drop=True)
print(f'样本 {len(sm):,}', flush=True)

feats31 = [f'f{j}' for j in range(31)]
NEW5 = ['f39_vol_diverge', 'f32_zha20', 'f34_overnight_share', 'f43_turn_cv20', 'f44_skew20']
NEW2 = ['kyle', 'amihud']
feats = feats31 + NEW5 + NEW2

dates = np.sort(sm['date'].unique()); split = dates[int(len(dates) * 0.8)]
tr = sm[sm['date'] < split].copy(); va = sm[sm['date'] >= split].copy()
print(f'切分日 {split} 训练 {len(tr):,} / 验证 {len(va):,}', flush=True)
assert tr['kyle'].notna().mean() > 0.5, '训练段 kyle 覆盖不足'

Xtr36 = tr[feats[:36]].to_numpy(dtype=float).copy()
Xtr38 = tr[feats].to_numpy(dtype=float).copy()
Xva36 = va[feats[:36]].to_numpy(dtype=float).copy()
Xva38 = va[feats].to_numpy(dtype=float).copy()
# 31 维护训练段 stats（clip+zscore），31+ NaN 直喂 —— 与生产逐字同
for j in range(31):
    v = Xtr38[:, j]; v = v[np.isfinite(v)]
    lo, hi = np.percentile(v, 1), np.percentile(v, 99)
    mu, sd = float(v.mean()), float(v.std())
    Xtr36[:, j] = Xtr38[:, j] = (np.clip(Xtr38[:, j], lo, hi) - mu) / sd
    Xva36[:, j] = Xva38[:, j] = (np.clip(Xva38[:, j], lo, hi) - mu) / sd
for X in (Xtr36, Xtr38): X[:, 31:] = np.where(np.isfinite(X[:, 31:]), X[:, 31:], np.nan)
for X in (Xva36, Xva38): X[:, 31:] = np.where(np.isfinite(X[:, 31:]), X[:, 31:], np.nan)

ytr_raw = tr['y'].to_numpy(dtype=float); yva_raw = va['y'].to_numpy(dtype=float)
# 臂C 标签：逐日截面 rank 分位（train 段内重算，不用全局）
tr['_rk'] = tr.groupby('date')['y'].rank(pct=True)
ytr_rank = tr['_rk'].to_numpy(dtype=float)
# 臂D：LambdaRank graded relevance = 逐日 y 十分位 0..9
tr['_gr'] = (tr.groupby('date')['y'].rank(pct=True) * 10).clip(0, 9.999).astype('int32')
ytr_gr = tr['_gr'].to_numpy()
grp_tr = tr.groupby('date', sort=True).size().to_numpy()
# 注意 groupby(date) 默认按 date 排序但 tr 本身要按同序排
order_tr = np.lexsort((np.arange(len(tr)), tr['date'].to_numpy()))
tr2 = tr.iloc[order_tr]; ytr_gr = ytr_gr[order_tr]
grp_tr = tr2.groupby('date', sort=True).size().to_numpy()
Xtr38_gr = Xtr38[order_tr]; ytr_rank = tr2['_rk'].to_numpy()

params = {'objective': 'regression', 'metric': 'l2', 'num_leaves': 15, 'learning_rate': 0.008,
 'feature_fraction': 0.6, 'bagging_fraction': 0.6, 'bagging_freq': 5, 'min_data_in_leaf': 300,
 'lambda_l1': 0.5, 'lambda_l2': 2.0, 'max_depth': 5, 'min_gain_to_split': 0.2, 'verbose': -1, 'num_threads': 8}
ROUNDS = 620
vdate = va['date'].to_numpy()
def daily_ic(p):
    out = {}
    for dte in np.unique(vdate):
        m = vdate == dte
        if m.sum() >= 200: out[str(dte)] = float(stats.spearmanr(p[m], yva_raw[m])[0])
    return pd.Series(out)
def paired(a, b, name):
    j = pd.concat([a, b], axis=1, keys=['a', 'b']).dropna()
    dd = (j['a'] - j['b']).to_numpy(); n = len(dd); mu = dd.mean(); x = dd - mu; l = 10
    gw = ((x*x).sum() + sum(2*(1-i/(l+1))*(x[i:]*x[:-i]).sum() for i in range(1, l+1)))/n
    se = np.sqrt(gw/n)
    print(f'{name} 配对差 {mu:+.5f} NW-t {mu/se:+.2f} (n={n})', flush=True)
    return float(mu), float(mu/se)

res = {}
preds = {}
# A: base36 L2
mA = lgb.train(params, lgb.Dataset(Xtr36, ytr_raw), num_boost_round=ROUNDS)
preds['A'] = daily_ic(mA.predict(Xva36)); preds['A'].to_csv(BASE + '/ic_A_base36_l2.csv')
print(f"A base36-L2 IC {preds['A'].mean():+.4f} 用时{time.time()-t0:.0f}s", flush=True)
# B: 38维 L2
mB = lgb.train(params, lgb.Dataset(Xtr38, ytr_raw), num_boost_round=ROUNDS)
preds['B'] = daily_ic(mB.predict(Xva38)); preds['B'].to_csv(BASE + '/ic_B_38_l2.csv')
print(f"B 38-L2 IC {preds['B'].mean():+.4f} 用时{time.time()-t0:.0f}s", flush=True)
paired(preds['B'], preds['A'], 'B-A(复现v4f)')
# C: 38维 L2 on rank 标签
pC = dict(params)
mC = lgb.train(pC, lgb.Dataset(Xtr38, ytr_rank), num_boost_round=ROUNDS)
preds['C'] = daily_ic(mC.predict(Xva38)); preds['C'].to_csv(BASE + '/ic_C_38_ranklabel.csv')
print(f"C 38-ranklabel IC {preds['C'].mean():+.4f} 用时{time.time()-t0:.0f}s", flush=True)
paired(preds['C'], preds['B'], 'C-B')
# D: LambdaRank
pD = {'objective': 'lambdarank', 'metric': 'ndcg', 'ndcg_eval_at': [100], 'label_gain': list(range(10)),
 'num_leaves': 15, 'learning_rate': 0.008, 'feature_fraction': 0.6, 'bagging_fraction': 0.6,
 'bagging_freq': 5, 'min_data_in_leaf': 300, 'lambda_l1': 0.5, 'lambda_l2': 2.0, 'max_depth': 5,
 'min_gain_to_split': 0.2, 'verbose': -1, 'num_threads': 8, 'lambdarank_truncation_level': 200}
mD = lgb.train(pD, lgb.Dataset(Xtr38, ytr_gr, group=grp_tr), num_boost_round=ROUNDS)
preds['D'] = daily_ic(mD.predict(Xva38)); preds['D'].to_csv(BASE + '/ic_D_38_lambdarank.csv')
print(f"D 38-lambdarank IC {preds['D'].mean():+.4f} 用时{time.time()-t0:.0f}s", flush=True)
paired(preds['D'], preds['B'], 'D-B')
paired(preds['D'], preds['A'], 'D-A')
paired(preds['C'], preds['A'], 'C-A')
best = max('ABCD', key=lambda k: preds[k].mean())
print(f'最优臂: {best}', flush=True)
for k in 'ABCD':
    mm = preds[k].copy(); mm.index = pd.to_datetime(mm.index)
    mo = mm.groupby(mm.index.to_period('M')).mean()
    print(k, '分月IC:', {str(a): round(b, 4) for a, b in mo.items()}, flush=True)
json.dump({k: {'ic_mean': float(preds[k].mean()), 'pos': float((preds[k] > 0).mean())} for k in 'ABCD'},
          open(BASE + '/v4h_results.json', 'w'), indent=1)
print(f'完成 {time.time()-t0:.0f}s', flush=True)
