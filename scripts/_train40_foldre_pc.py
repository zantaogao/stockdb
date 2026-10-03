"""折选规模+全年重训+2026闭卷终判 (2026-10-02 用户拍板: 训19-25, 树数方案我定)
设计:
  规模: 2022/2023/2024/2025 各做一次早停折(训练段=该年前), best_iter取中位数, 限幅[20,3000]
  两标度: z=clip+zscore(生产口径) / r=当日截面rank(新臂, 标签也rank)
  两臂:  A=生产29维(f0..25+f31/32/33), D=27维(f0..25+mf20)
  终训: 2019-01~2025-12 全段, 固定树数无早停; 测试=2026(138日)
  学习参数=生产params逐字不动. 判据: D-A配对日差 NW-t(lag5)>=2.
产出: foldre_*_ic_*.csv, foldre_cmp.json, foldre_trees.json"""
import json, time
import numpy as np, pandas as pd, lightgbm as lgb
from scipy import stats as st
from pathlib import Path
BASE = Path('C:/Users/zantan/mf40')
params = dict(objective='regression', metric='l2', num_leaves=15, learning_rate=0.01,
    feature_fraction=0.6, bagging_fraction=0.6, bagging_freq=5, min_data_in_leaf=300,
    lambda_l1=0.5, lambda_l2=2.0, max_depth=5, min_gain_to_split=0.2, verbose=1, num_threads=8)
F26 = ['f%d' % j for j in range(26)]
ARMS = {'A': F26 + ['f31', 'f32', 'f33'], 'D': F26 + ['mf20']}
TEST_START = '20260101'
FOLDS = [('2022', '20220101'), ('2023', '20230101'), ('2024', '20240101'), ('2025', '20250101')]

df = pd.read_parquet(BASE / 'samples_40d_mf.parquet')
df['date'] = df['date'].astype(str).str.replace('-', '', regex=False)
df = df.sort_values(['date', 'code']).reset_index(drop=True)
dts = df.date.to_numpy()
y_raw = df.y40.to_numpy(float)
print(f'样本 {len(df):,} 日 {df.date.nunique()}', flush=True)

# 截面rank一次算好(按天分组, 与子集切片等价): 列并集30列 float32 ~1G
def cs_rank(mat, day_ids):
    out = np.empty(mat.shape, np.float32)
    bounds = np.flatnonzero(np.r_[True, day_ids[1:] != day_ids[:-1]])
    b = list(bounds) + [len(day_ids)]
    for i in range(len(bounds)):
        blk = mat[b[i]:b[i+1]]
        nanm = ~np.isfinite(blk)
        args = np.argsort(np.where(nanm, np.inf, blk), axis=0, kind='stable')
        ranks = np.empty_like(args)
        np.put_along_axis(ranks, args, np.arange(blk.shape[0])[:, None], axis=0)
        r = ranks / max(blk.shape[0] - 1, 1)
        r[nanm] = 0.5
        out[b[i]:b[i+1]] = r
    return out
day_ids = pd.factorize(dts, sort=True)[0]
cols = sorted(set(ARMS['A'] + ARMS['D']), key=lambda c: (c != 'mf20', c))
M = df[cols].to_numpy(np.float64)
R = cs_rank(M, day_ids)
RANK = {c: R[:, cols.index(c)] for c in cols}
y_rank = cs_rank(y_raw[:, None], day_ids)[:, 0]
print('截面rank完成', flush=True)

def getX(arm, scale, mask):
    if scale == 'z':
        return df.loc[mask, ARMS[arm]].to_numpy(float)
    return np.column_stack([RANK[c][mask] for c in ARMS[arm]])

def daily_ic(pred, dmask_days, y):
    recs = []
    for d in np.unique(dmask_days):
        m = dmask_days == d
        if m.sum() >= 200:
            recs.append({'date': str(d), 'rank_ic': float(st.spearmanr(pred[m], y[m])[0])})
    return recs

trees = {}
for scale in ['z', 'r']:
    for arm in ['A', 'D']:
        feats = ARMS[arm]; its = []
        for name, fold_start in FOLDS:
            trm = dts < fold_start
            esm = (dts >= fold_start) & (dts < str(int(fold_start[:4]) + 1) + '0101')
            Xt, Xe = getX(arm, scale, trm), getX(arm, scale, esm)
            if scale == 'z':
                lo, hi = np.percentile(Xt, 1, 0), np.percentile(Xt, 99, 0)
                mu, sd = Xt.mean(0), Xt.std(0) + 1e-12
                Xt = (np.clip(Xt, lo, hi) - mu) / sd
                Xe = (np.clip(Xe, lo, hi) - mu) / sd
            Xt, Xe = np.nan_to_num(Xt, 0.0), np.nan_to_num(Xe, 0.0)
            yt = y_raw[trm] if scale == 'z' else y_rank[trm]
            ye = y_raw[esm] if scale == 'z' else y_rank[esm]
            m = lgb.train(params, lgb.Dataset(Xt, yt), num_boost_round=6000,
                valid_sets=[lgb.Dataset(Xe, ye)], valid_names=['es'],
                callbacks=[lgb.early_stopping(50, verbose=False)])
            its.append(int(m.best_iteration)); print(f'[{scale}-{arm}] fold{name} best={m.best_iteration}', flush=True)
            del Xt, Xe
        trees[f'{scale}{arm}'] = int(np.clip(np.median(its), 20, 3000))
        print(f'[{scale}-{arm}] 中位树数 {trees[f"{scale}{arm}"]} (folds {its})', flush=True)
json.dump(trees, open(BASE / 'foldre_trees.json', 'w'), indent=1)

fin = {}
for scale in ['z', 'r']:
    for arm in ['A', 'D']:
        trm = dts < TEST_START; tem = dts >= TEST_START
        Xt = getX(arm, scale, trm); Xe = getX(arm, scale, tem)
        if scale == 'z':
            lo, hi = np.percentile(Xt, 1, 0), np.percentile(Xt, 99, 0)
            mu, sd = Xt.mean(0), Xt.std(0) + 1e-12
            Xt = (np.clip(Xt, lo, hi) - mu) / sd; Xe = (np.clip(Xe, lo, hi) - mu) / sd
        Xt, Xe = np.nan_to_num(Xt, 0.0), np.nan_to_num(Xe, 0.0)
        t0 = time.time()
        m = lgb.train(params, lgb.Dataset(Xt, y_raw[trm] if scale == 'z' else y_rank[trm]),
                      num_boost_round=trees[f'{scale}{arm}'])
        pred = m.predict(Xe)
        recs = daily_ic(pred, dts[tem], y_raw[tem])
        pd.DataFrame(recs).to_csv(BASE / f'foldre_ic_{scale}{arm}.csv', index=False)
        ics = [r['rank_ic'] for r in recs]
        fin[f'{scale}{arm}'] = recs
        top = sorted(zip(m.feature_importance('gain'), ARMS[arm]), reverse=True)[:4]
        print(f'[{scale}{arm}] {time.time()-t0:.0f}s 树{trees[f"{scale}{arm}"]} 2026日均IC {np.mean(ics):+.4f} '
              f'top4={[(f, round(g)) for g, f in top]}', flush=True)
        del Xt, Xe, pred

def nw_t(x, lag=5):
    x = np.asarray(x, float); n = len(x); xc = x - x.mean(); s0 = (xc * xc).mean()
    lv = max(s0 + 2 * sum((xc[l:] * xc[:-l]).mean() for l in range(1, lag + 1)), s0)
    return float(x.mean() / np.sqrt(lv / n)) if lv > 1e-15 else float('nan')

def pair(a, b, out):
    ca = {r['date']: r['rank_ic'] for r in fin[a]}; cb = {r['date']: r['rank_ic'] for r in fin[b]}
    com = sorted(set(ca) & set(cb)); dif = np.array([cb[k] - ca[k] for k in com])
    t = nw_t(dif)
    print(f'{out}: 日均差 {dif.mean():+.5f} NW-t {t:+.2f} 为正 {(dif>0).mean()*100:.0f}%', flush=True)
    json.dump(dict(n=len(com), mean_diff=float(dif.mean()), nw_t=t), open(BASE / f'foldre_{out}.json', 'w'), indent=1)
    return dif, com

print('=== 判据(同标度 D-A = mf20增量) ===', flush=True)
pair('zA', 'zD', 'cmp_z_DA'); pair('rA', 'rD', 'cmp_r_DA')
print('=== 参考(同臂 r-z = rank化效应) ===', flush=True)
difA, comA = pair('zA', 'rA', 'cmp_A_zr'); pair('zD', 'rD', 'cmp_D_zr')
print('=== 分月 (rA-rD vs zA-zD) ===', flush=True)
difD, comD = None, None
for q in ['2026' + m for m in ['01','02','03','04','05','06','07','08','09']]:
    mA = [i for i, k in enumerate(comA) if k.startswith(q)]
    ca = {r['date']: r['rank_ic'] for r in fin['zA']}; ra_ = {r['date']: r['rank_ic'] for r in fin['rA']}
    if mA:
        cd = {r['date']: r['rank_ic'] for r in fin['zD']}; rd_ = {r['date']: r['rank_ic'] for r in fin['rD']}
        print(f'  {q}: A臂rank效应 {np.mean([ra_[comA[i]]-ca[comA[i]] for i in mA]):+.5f}  '
              f'D臂rank效应 {np.mean([rd_[comA[i]]-cd[comA[i]] for i in mA]):+.5f}', flush=True)
print('DONE', flush=True)
