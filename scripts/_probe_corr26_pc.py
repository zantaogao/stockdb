"""26维相关因子分组 (2026-10-02)
截面rank后算列间相关(|rho|>=0.75成边, 并查集聚群), 附各列gain占比标出每簇该留谁.
训练段2019-2025. 产出 pc:corr26.log"""
import numpy as np, pandas as pd, lightgbm as lgb
from scipy import stats as st
df = pd.read_parquet('C:/Users/zantan/mf40/samples_40d_mf.parquet')
df['date'] = df['date'].astype(str).str.replace('-', '', regex=False)
df = df[df.date < '20260101'].sort_values(['date', 'code']).reset_index(drop=True)
BK = [0,1,2,3,4,5,6,7,8,9,11,12,13,14,15,18,19,20,21,22,23,24,25,26,28,29]
N38 = ['chg5','chg10','chg20','chg60','chg120','d5','d10','d20','d60','d120','bull1','bull2',
       'rr20振幅','std20','vr量比','pos位置','nh新高','vpc','c1d','c3d','ep','bp','ln_cap',
       'ex5','ex10','ex20','skew20','kurt20','dn连阴','up_ratio10','vol_chg','rel_str',
       'kurt60','slope5','slope10','accel','vp缩','vp背离']
NAME = {f'f{i}': N38[BK[i]] for i in range(26)}
NAME.update({'f31': 'kdj_k', 'f32': 'cci', 'f33': 'rsi12', 'mf20': 'mf20资金流'})
cols = ['f%d' % i for i in range(26)] + ['f31', 'f32', 'f33', 'mf20']
X = df[cols].to_numpy(np.float64)
dts = df.date.to_numpy(); day_ids = pd.factorize(dts, sort=True)[0]
# 截面rank
Rk = np.empty(X.shape, np.float32)
bounds = list(np.flatnonzero(np.r_[True, day_ids[1:] != day_ids[:-1]])) + [len(day_ids)]
for i in range(len(bounds) - 1):
    blk = X[bounds[i]:bounds[i+1]]
    nanm = ~np.isfinite(blk)
    args = np.argsort(np.where(nanm, np.inf, blk), axis=0, kind='stable')
    ranks = np.empty_like(args)
    np.put_along_axis(ranks, args, np.arange(blk.shape[0])[:, None], axis=0)
    r = ranks / max(blk.shape[0] - 1, 1); r[nanm] = 0.5
    Rk[bounds[i]:bounds[i+1]] = r
del X
C = np.corrcoef(Rk.T)
n = len(cols)
# 并查集
par = list(range(n))
def find(a):
    while par[a] != a: par[a] = par[par[a]]; a = par[a]
    return a
pairs = []
for i in range(n):
    for j in range(i + 1, n):
        if abs(C[i, j]) >= 0.75:
            pairs.append((cols[i], cols[j], float(C[i, j])))
            a, b = find(i), find(j); par[a] = b
# gain(同一口径309棵树)
y = np.clip(df.y40.to_numpy(float), -1, 3)
Xz = Rk.astype(np.float64)
m = lgb.train(dict(objective='regression', metric='l2', num_leaves=15, learning_rate=0.01,
    feature_fraction=0.6, bagging_fraction=0.6, bagging_freq=5, min_data_in_leaf=300,
    lambda_l1=0.5, lambda_l2=2.0, max_depth=5, min_gain_to_split=0.2, verbose=-1, num_threads=8),
    lgb.Dataset(Xz, y), num_boost_round=309)
g = m.feature_importance('gain'); gs = {c: float(g[k]) for k, c in enumerate(cols)}
s = g.sum()
groups = {}
for i in range(n):
    groups.setdefault(find(i), []).append(cols[i])
print('=== 簇(|截面rank相关|>=0.75 连通) ===', flush=True)
for k, mem in sorted(groups.items(), key=lambda kv: -max(gs[c] for c in kv[1])):
    if len(mem) == 1:
        print(f'独立列: {mem[0]} ({NAME.get(int(mem[0][1:]) if mem[0]!="mf20" else 99, mem[0])}) gain {gs[mem[0]]/s*100:.2f}%', flush=True)
    else:
        tag = [f'{c}:{NAME.get(int(c[1:]) if c!="mf20" else 99, c)} g{gs[c]/s*100:.1f}%' for c in mem]
        print(f'簇: {" | ".join(tag)}', flush=True)
print('=== 强对清单(按|rho|降序) ===', flush=True)
for a, b, r in sorted(pairs, key=lambda t: -abs(t[2])):
    print(f'{a} ~ {b}: rho={r:+.3f} (gain {gs[a]/s*100:.2f}%/{gs[b]/s*100:.2f}%)', flush=True)
print('DONE', flush=True)
