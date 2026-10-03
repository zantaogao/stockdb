"""V2臂: f19格从市值(ln_cap)换成估值(ep), 列数不变 (2026-10-02 用户本意: 换回估值)
对照基准A=生产29维(f19=ln_cap). z标度309棵, 训19-25, 2026闭卷.
看点: 估值列坐上来后 gain占比/集中度; 2026 IC对比A; 小票偏好是否消失. 产出 pc: epcap.log"""
import numpy as np, pandas as pd, lightgbm as lgb
from scipy import stats as st
df = pd.read_parquet('C:/Users/zantan/mf40/samples_40d_mf.parquet')
df['date'] = df['date'].astype(str).str.replace('-', '', regex=False)
df = df.sort_values(['date', 'code']).reset_index(drop=True)
df['f19ep'] = df['f17']  # 顶替格: ep(=1/PE估值)
feats = ['f%d' % j for j in range(19)] + ['f19ep'] + ['f%d' % j for j in range(20, 26)] + ['f31', 'f32', 'f33']
dts = df.date.to_numpy(); y = df.y40.to_numpy(float)
raw_cap = df.f19.to_numpy(float, copy=True)
c20 = df.f2.to_numpy(float, copy=True)
tr = dts < '20260101'; te = ~tr
def zfit(cols, rounds=309):
    Xt = df.loc[tr, cols].to_numpy(float).copy()
    lo, hi = np.nanpercentile(Xt, 1, 0), np.nanpercentile(Xt, 99, 0)
    mu = np.nanmean(Xt, 0); sd = np.nanstd(Xt, 0) + 1e-12
    Xe = df.loc[te, cols].to_numpy(float).copy()
    Xe = np.clip(Xe, lo, hi); Xe = np.where(np.isfinite(Xe), (Xe - mu) / sd, 0.0)
    Xz = (np.clip(Xt, lo, hi) - mu) / sd; Xz = np.where(np.isfinite(Xz), Xz, 0.0)
    m = lgb.train(dict(objective='regression', metric='l2', num_leaves=15, learning_rate=0.01,
        feature_fraction=0.6, bagging_fraction=0.6, bagging_freq=5, min_data_in_leaf=300,
        lambda_l1=0.5, lambda_l2=2.0, max_depth=5, min_gain_to_split=0.2, verbose=-1, num_threads=8),
        lgb.Dataset(Xz, np.clip(y[tr], -1, 3)), num_boost_round=rounds)
    return m, m.predict(Xe)
mV, pV = zfit(feats); print('V2(f19格=ep)完成', flush=True)
g = mV.feature_importance('gain'); s = g.sum(); order = np.argsort(g)[::-1]
print('=== V2臂 gain top10 (f19ep=顶替的估值格) ===', flush=True)
cum = 0
for r, i in enumerate(order[:10], 1):
    cum += g[i]
    print(f'{r:2d} {feats[i]} {float(g[i]):.3e} 累计 {float(cum/s)*100:.1f}%', flush=True)
mA, pA = zfit(['f%d' % j for j in range(26)] + ['f31', 'f32', 'f33']); print('A(29维市值版)完成', flush=True)
dte = dts[te]; yte = y[te]
lnk = np.nan_to_num(raw_cap[te], nan=22.0); cc = np.nan_to_num(c20[te], nan=0.0)
icV = {}
for d in np.unique(dte):
    k = dte == d
    if k.sum() >= 200: icV[str(d)] = float(st.spearmanr(pV[k], yte[k])[0])
icA_d = {}
for d in np.unique(dte):
    k = dte == d
    if k.sum() >= 200: icA_d[str(d)] = float(st.spearmanr(pA[k], yte[k])[0])
com = sorted(set(icA_d) & set(icV)); dif = np.array([icV[k] - icA_d[k] for k in com])
x = dif - dif.mean(); s0 = (x * x).mean()
lv = max(s0 + 2 * sum((x[l:] * x[:-l]).mean() for l in range(1, 6)), s0)
print(f'=== 2026: A日均 {np.mean([icA_d[k] for k in com]):+.4f}  V2日均 {np.mean([icV[k] for k in com]):+.4f}  '
      f'配对差 {dif.mean():+.5f} NW-t {dif.mean()/np.sqrt(lv/len(dif)):+.2f} 为正 {(dif>0).mean()*100:.0f}% ===', flush=True)
print('=== 月度: corr(分,市值) / corr(分,chg20) / top10%近20涨幅 vs 市场 ===', flush=True)
for mo in ['2026' + m2 for m2 in ['01','02','03','04','05','06','07']]:
    a = []
    for d in np.unique(dte[(dte >= mo + '01') & (dte < mo + '32')]):
        k = dte == d
        if k.sum() < 200: continue
        top = np.argsort(pV[k])[-int(k.sum() * 0.1):]
        a.append([st.spearmanr(pV[k], lnk[k])[0], st.spearmanr(pV[k], cc[k])[0],
                  cc[k][top].mean() * 100, cc[k].mean() * 100])
    A = np.array(a)
    print(f'{mo}: corr市值 {A[:,0].mean():+.2f}  corr_chg20 {A[:,1].mean():+.2f}  '
          f'top10%近20涨幅 {A[:,2].mean():+.1f}% vs 市场 {A[:,3].mean():+.1f}%', flush=True)
print('DONE', flush=True)
