"""验证'模型越跌分越高' + ep单列2026月度IC (2026-10-02)
zA口径静态模型(309棵树,训19-25)预测2026, 逐日截面算:
  corr(pred, chg20) —— 负=模型偏爱近期下跌票
  corr(pred, ep)     —— 正=模型偏爱低估值
  IC(ep, y40)        —— ep单列选股灵不灵
  IC(chg20, y40)     —— 跌了后面涨不涨(反转效应本身)
+ top10%组合画像: 模型选中票的近20日涨幅均值 vs 全市场均值
产出 pc:epdrop.log"""
import numpy as np, pandas as pd, lightgbm as lgb
from scipy import stats as st
df = pd.read_parquet('C:/Users/zantan/mf40/samples_40d_mf.parquet')
df['date'] = df['date'].astype(str).str.replace('-', '', regex=False)
df = df.sort_values(['date', 'code']).reset_index(drop=True)
feats = ['f%d' % j for j in range(26)] + ['f31', 'f32', 'f33']
dts = df.date.to_numpy(); y = df.y40.to_numpy(float)
tr = dts < '20260101'; te = ~tr
Xt = df.loc[tr, feats].to_numpy(float).copy()
lo, hi = np.nanpercentile(Xt, 1, 0), np.nanpercentile(Xt, 99, 0)
mu = np.nanmean(Xt, 0); sd = np.nanstd(Xt, 0) + 1e-12
Xt = np.clip(Xt, lo, hi); Xt = np.where(np.isfinite(Xt), (Xt - mu) / sd, 0.0)
m = lgb.train(dict(objective='regression', metric='l2', num_leaves=15, learning_rate=0.01,
    feature_fraction=0.6, bagging_fraction=0.6, bagging_freq=5, min_data_in_leaf=300,
    lambda_l1=0.5, lambda_l2=2.0, max_depth=5, min_gain_to_split=0.2, verbose=-1, num_threads=8),
    lgb.Dataset(Xt, np.clip(y[tr], -1, 3)), num_boost_round=309)
Xe = df.loc[te, feats].to_numpy(float).copy()
Xe = np.clip(Xe, lo, hi); Xe = np.where(np.isfinite(Xe), (Xe - mu) / sd, 0.0)
pred = m.predict(Xe)
print(f'训练完成 预测{len(pred):,}', flush=True)
dte = dts[te]; yte = y[te]
rows = []
for mo in ['2026' + m2 for m2 in ['01','02','03','04','05','06','07']]:
    acc = []
    days = np.unique(dte[(dte >= mo + '01') & (dte < mo + '32')])
    for d in days:
        k = dte == d
        if k.sum() < 200: continue
        p_, y_, e_, c20_ = pred[k], yte[k], Xe[k, 19], Xe[k, 2]  # z后列: 19=ep, 2=chg20
        n = len(p_); cut = int(n * 0.1)
        top = np.argsort(p_)[-cut:]
        acc.append([st.spearmanr(p_, c20_)[0], st.spearmanr(p_, e_)[0],
                    st.spearmanr(e_, y_)[0], st.spearmanr(c20_, y_)[0],
                    c20_[top].mean(), c20_.mean()])
    a = np.array(acc)
    print(f'{mo}: corr(分,近20日涨幅) {a[:,0].mean():+.3f}  corr(分,ep) {a[:,1].mean():+.3f}  '
          f'ep单列IC {a[:,2].mean():+.4f}  chg20反转IC {a[:,3].mean():+.4f}  '
          f'top10%近20日涨幅 {a[:,4].mean()*100:+.1f}% vs 市场 {a[:,5].mean()*100:+.1f}%', flush=True)
print('DONE', flush=True)
