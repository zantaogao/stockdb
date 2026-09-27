# v7 vs 旧40d 生产口径对账（零改码方案验证，2026-09-26）
# 命题: 生产 f40 = _standardize(feat_29) = BASE_KEEP26 + 因子3，v7 第30维 ex5 用 stats 默认值(0) → 数学上 = 特征缺失时的 LightGBM 默认分裂行为
# 验证: ① 新口径样本上模拟两种口径的 v7 分数, 对真实y40算IC ② 新旧40d模型生产口径分数分布对比
import json, numpy as np, pandas as pd
from pathlib import Path
from scipy import stats
import lightgbm as lgb
B = Path.home()/'.hermes/stockdb/analysis/retrain_20260926'
M = Path.home()/'.hermes/stockdb/models'
df = pd.read_parquet(B/'samples_40d_v7.parquet'); df['date'] = df['date'].astype(str)
feats = ['f%d'%j for j in range(26)] + ['f31','f32','f33','f34']
dts = np.sort(df['date'].unique()); split = dts[int(len(dts)*0.8)]
va = df[df['date'] >= split].reset_index(drop=True)
sd_v7 = json.load(open(B/'v40_v7_stats.json'))
def std29(frame):  # 生产 _standardize 逐字复刻（缺 key 的维原样保留）
    X = frame[feats].to_numpy(float).copy()
    for j in range(30):
        k = f'feat_{j}'
        if k in sd_v7:
            s = sd_v7[k]
            if s['std'] > 0:
                X[:,j] = np.clip(X[:,j], s['low'], s['high']); X[:,j] = (X[:,j]-s['mean'])/s['std']
    return np.nan_to_num(X, nan=0.0)
v7 = lgb.Booster(model_file=str(B/'lgb_reg_40d_v7.txt'))
X_real = std29(va)                       # ex5 真值
X_zero = X_real.copy(); X_zero[:,29] = 0.0   # 生产缺省模拟: ex5=0
y = va['y40'].to_numpy(float); d = va['date'].to_numpy()
def daily_ic(p):
    return np.array([stats.spearmanr(p[d==dd], y[d==dd])[0] for dd in np.unique(d) if (d==dd).sum()>=200])
ic_a, ic_b = daily_ic(v7.predict(X_real)), daily_ic(v7.predict(X_zero))
spear_prod = stats.spearmanr(v7.predict(X_real), v7.predict(X_zero))[0]
print(f'v7 ex5真值口径 日均IC {ic_a.mean():+.4f} 正占比{(ic_a>0).mean()*100:.0f}%')
print(f'v7 ex5=0(生产模拟) 日均IC {ic_b.mean():+.4f} 正占比{(ic_b>0).mean()*100:.0f}%')
print(f'两口径分数 Spearman {spear_prod:.4f}（差值来自 ex5 维，ex5 split 贡献 34 次/165树）')
# 旧模型生产口径（feat_29 前23维喂旧模型，即现行 _standardize+旧stats）
old = lgb.Booster(model_file=str(M/'retired_20260926/lgb_reg_40d_new_stkfactor.txt'))
sd_old = json.load(open(M/'retired_20260926/v6_norm_stats_40d_tushare_v2_stkfactor.json'))
def std_old(frame):
    X = frame[['f%d'%j for j in range(23)] + ['f31','f32','f33']].to_numpy(float).copy()  # 生产: feat_29 前23维? 旧模型实际吃 feat_29 全29维
    return X
X_old = np.column_stack([va[f'f{j}'].to_numpy(float) for j in range(26)] + [va[f'f3{j}'].to_numpy(float) for j in (1,2,3)])
X_old2 = X_old.copy()
for j in range(29):
    k = f'feat_{j}'
    if k in sd_old and sd_old[k]['std'] > 0:
        X_old2[:,j] = np.clip(X_old2[:,j], sd_old[k]['low'], sd_old[k]['high']); X_old2[:,j] = (X_old2[:,j]-sd_old[k]['mean'])/sd_old[k]['std']
X_old2 = np.nan_to_num(X_old2, nan=0.0)
ic_old = daily_ic(old.predict(X_old2))
print(f'旧40d 生产口径 日均IC {ic_old.mean():+.4f} 正占比{(ic_old>0).mean()*100:.0f}%')
print(f'新旧40d生产口径分数 Spearman {stats.spearmanr(old.predict(X_old2), v7.predict(X_zero))[0]:.4f}')
print(f'分数分布: 旧 mean={old.predict(X_old2).mean():.3f} std={old.predict(X_old2).std():.3f} | v7(ex5=0) mean={v7.predict(X_zero).mean():.3f} std={v7.predict(X_zero).std():.3f}')
