"""2026月度滚动重训 walk-forward (2026-10-02 用户拍板继续优化)
规则: 2026每月m的分数只由训练于 <m月初 全部样本的模型打; 月度重训=生产新候选节奏.
臂: zA=生产口径29维 z标度 / rA=29维rank / rD=27维(+mf20)rank
树数: 折投票中位数(rA=663, rD=830, zA=309, 已定不复用2026调)
判据: 2026逐月日IC + rD-rA配对(mf20在新鲜模型下增量) + rA vs zA(管线增量在滚动下是否保住)
产出: wf_ic_{arm}.csv, wf_cmp.json"""
import json, time
import numpy as np, pandas as pd, lightgbm as lgb
from scipy import stats as st
from pathlib import Path
BASE = Path('C:/Users/zantan/mf40')
params = dict(objective='regression', metric='l2', num_leaves=15, learning_rate=0.01,
    feature_fraction=0.6, bagging_fraction=0.6, bagging_freq=5, min_data_in_leaf=300,
    lambda_l1=0.5, lambda_l2=2.0, max_depth=5, min_gain_to_split=0.2, verbose=-1, num_threads=8)
F26 = ['f%d' % j for j in range(26)]
ARMS = {'zA': F26 + ['f31', 'f32', 'f33'], 'rA': F26 + ['f31', 'f32', 'f33'], 'rD': F26 + ['mf20']}
TREES = {'zA': 309, 'rA': 663, 'rD': 830}
MONTHS = ['2026' + m for m in ['01', '02', '03', '04', '05', '06', '07']]

df = pd.read_parquet(BASE / 'samples_40d_mf.parquet')
df['date'] = df['date'].astype(str).str.replace('-', '', regex=False)
df = df[df.date < '20260801'].sort_values(['date', 'code']).reset_index(drop=True)
dts = df.date.to_numpy(); y_raw = df.y40.to_numpy(float)
day_ids = pd.factorize(dts, sort=True)[0]
print(f'样本 {len(df):,} 截至 {dts.max()}', flush=True)

def cs_rank(mat):
    out = np.empty(mat.shape, np.float32)
    bounds = list(np.flatnonzero(np.r_[True, day_ids[1:] != day_ids[:-1]])) + [len(day_ids)]
    for i in range(len(bounds) - 1):
        blk = mat[bounds[i]:bounds[i+1]]
        nanm = ~np.isfinite(blk)
        args = np.argsort(np.where(nanm, np.inf, blk), axis=0, kind='stable')
        ranks = np.empty_like(args)
        np.put_along_axis(ranks, args, np.arange(blk.shape[0])[:, None], axis=0)
        r = ranks / max(blk.shape[0] - 1, 1); r[nanm] = 0.5
        out[bounds[i]:bounds[i+1]] = r
    return out

cols = F26 + ['f31', 'f32', 'f33', 'mf20']
M = df[cols].to_numpy(np.float64)
R = cs_rank(M); RD = {c: R[:, cols.index(c)] for c in cols}
del M, R
print('rank完成', flush=True)

recs = {a: [] for a in ARMS}
for mth in MONTHS:
    trm = dts < (mth + '01')
    tem = (dts >= mth + '01') & (dts < mth + '32')
    for arm in ARMS:
        feats = ARMS[arm]
        if arm == 'zA':
            Xt = df.loc[trm, feats].to_numpy(float).copy()
            lo, hi = np.nanpercentile(Xt, 1, 0), np.nanpercentile(Xt, 99, 0)
            mu = np.nanmean(Xt, 0); sd = np.nanstd(Xt, 0) + 1e-12
            Xt = np.clip(Xt, lo, hi); Xt = np.where(np.isfinite(Xt), (Xt - mu) / sd, 0.0)
            Xe = df.loc[tem, feats].to_numpy(float).copy()
            Xe = np.clip(Xe, lo, hi); Xe = np.where(np.isfinite(Xe), (Xe - mu) / sd, 0.0)
            yt = y_raw[trm]; yte = y_raw[tem]
        else:
            Xt = np.column_stack([RD[c][trm] for c in feats])
            Xe = np.column_stack([RD[c][tem] for c in feats])
            yt = np.clip(y_raw[trm], -1, 3)  # 标签截尾防肥尾(y40 40日复利), 不用rank保对日IC可比
            yte = y_raw[tem]
        t0 = time.time()
        m = lgb.train(params, lgb.Dataset(Xt, yt), num_boost_round=TREES[arm])
        pred = m.predict(Xe)
        dte = dts[tem]
        mm = [(str(d), float(st.spearmanr(pred[dte == d], y_raw[tem][dte == d])[0]))
              for d in np.unique(dte) if (dte == d).sum() >= 200]
        recs[arm] += [{'date': d, 'rank_ic': v} for d, v in mm]
        print(f'{mth} {arm}: {time.time()-t0:.0f}s 月均IC {np.mean([v for _, v in mm]):+.4f} ({len(mm)}日)', flush=True)
        del Xt, Xe, pred, m
for arm in ARMS:
    pd.DataFrame(recs[arm]).to_csv(BASE / f'wf_ic_{arm}.csv', index=False)

def nw_t(x, lag=5):
    x = np.asarray(x, float); n = len(x); xc = x - x.mean(); s0 = (xc * xc).mean()
    lv = max(s0 + 2 * sum((xc[l:] * xc[:-l]).mean() for l in range(1, lag + 1)), s0)
    return float(x.mean() / np.sqrt(lv / n)) if lv > 1e-15 else float('nan')

def pair(a, b, out):
    ca = {r['date']: r['rank_ic'] for r in recs[a]}; cb = {r['date']: r['rank_ic'] for r in recs[b]}
    com = sorted(set(ca) & set(cb)); dif = np.array([cb[k] - ca[k] for k in com])
    t = nw_t(dif)
    print(f'{out}: 日均差 {dif.mean():+.5f} NW-t {t:+.2f} 为正 {(dif>0).mean()*100:.0f}% 全期IC a={np.mean([ca[k] for k in com]):+.4f} b={np.mean([cb[k] for k in com]):+.4f}', flush=True)
    json.dump(dict(n=len(com), mean_diff=float(dif.mean()), nw_t=t), open(BASE / f'wf_{out}.json', 'w'), indent=1)
print('=== 判据 ===', flush=True)
pair('rA', 'rD', 'cmp_rD_vs_rA')
pair('zA', 'rA', 'cmp_rA_vs_zA')
pair('zA', 'rD', 'cmp_rD_vs_zA')
print('DONE', flush=True)
