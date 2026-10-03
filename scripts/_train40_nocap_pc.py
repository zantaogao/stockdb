"""砍市值列对照臂 V (2026-10-02 用户拍板: 把市值改回估值训一版)
V臂 = zA(生产29维) 去掉 f19(ln_cap) = 28维(估值ep/bp仍在). z标度309棵, 训19-25, 2026闭卷.
输出: V臂日IC vs zA配对NW-t; gain分布(头列换谁/集中度); 月度corr(分,市值)/corr(分,chg20)/top10%画像——
     检验"偏爱小票"是列带进来的还是模型从别处学的. 产出 pc: nocap.log"""
import numpy as np, pandas as pd, lightgbm as lgb
from scipy import stats as st
df = pd.read_parquet('C:/Users/zantan/mf40/samples_40d_mf.parquet')
df['date'] = df['date'].astype(str).str.replace('-', '', regex=False)
df = df.sort_values(['date', 'code']).reset_index(drop=True)
feats = ['f%d' % j for j in range(26)] + ['f31', 'f32', 'f33']
VF = [f for f in feats if f != 'f19']
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
mA, pA = zfit(feats); print('A(29维)重训完成(基准复现)', flush=True)
mV, pV = zfit(VF); print('V(28维无市值)完成', flush=True)

g = mV.feature_importance('gain'); s = g.sum(); order = np.argsort(g)[::-1]
print('=== V臂 gain top10 ===', flush=True)
cum = 0
for r, i in enumerate(order[:10], 1):
    cum += g[i]
    print(f'{r:2d} {VF[i]} {float(g[i]):.3e} 累计 {float(cum/s)*100:.1f}%', flush=True)

dte = dts[te]; yte = y[te]
lnk = np.nan_to_num(raw_cap[te], nan=22.0); cc = np.nan_to_num(c20[te], nan=0.0)
def daily_ic(pred):
    out = {}
    for d in np.unique(dte):
        k = dte == d
        if k.sum() >= 200: out[str(d)] = float(st.spearmanr(pred[k], yte[k])[0])
    return out
icA, icV = daily_ic(pA), daily_ic(pV)
com = sorted(set(icA) & set(icV)); dif = np.array([icV[k] - icA[k] for k in com])
x = dif - dif.mean(); s0 = (x * x).mean()
lv = max(s0 + 2 * sum((x[l:] * x[:-l]).mean() for l in range(1, 6)), s0)
print(f'=== 2026: A日均 {np.mean([icA[k] for k in com]):+.4f}  V日均 {np.mean([icV[k] for k in com]):+.4f}  '
      f'配对差 {dif.mean():+.5f} NW-t {dif.mean()/np.sqrt(lv/len(dif)):+.2f} 为正 {(dif>0).mean()*100:.0f}% ===', flush=True)
print('=== 月度画像 A vs V (corr分-市值 / corr分-chg20 / top10%近20涨幅 / top10%均市值亿) ===', flush=True)
for mo in ['2026' + m2 for m2 in ['01','02','03','04','05','06','07']]:
    aA = []; aV = []
    for d in np.unique(dte[(dte >= mo + '01') & (dte < mo + '32')]):
        k = dte == d
        if k.sum() < 200: continue
        for pred, acc in ((pA, aA), (pV, aV)):
            top = np.argsort(pred[k])[-int(k.sum() * 0.1):]
            acc.append([st.spearmanr(pred[k], lnk[k])[0], st.spearmanr(pred[k], cc[k])[0],
                        cc[k][top].mean() * 100, np.exp(lnk[k][top].mean()) / 1e8])
    A = np.array(aA); V = np.array(aV)
    print(f'{mo}: A {A[:,0].mean():+.2f}/{A[:,1].mean():+.2f}/{A[:,2].mean():+.1f}%/{np.mean(A[:,3]):.0f}亿   '
          f'V {V[:,0].mean():+.2f}/{V[:,1].mean():+.2f}/{V[:,2].mean():+.1f}%/{np.mean(V[:,3]):.0f}亿  '
          f'(市场均市值 {np.exp(lnk[(dte>=mo+"01")&(dte<mo+"32")].mean())/1e8:.0f}亿)', flush=True)
pd.DataFrame([{'date': k, 'rank_ic': icV[k]} for k in com]).to_csv('C:/Users/zantan/mf40/nocap_ic_V.csv', index=False)
print('DONE', flush=True)
