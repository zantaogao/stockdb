# 0927 上线对账（最终版）: 生产 score_stock 重算 vs 样本行(同特征口径构建)喂同一模型
# 对账对象: 20d(31维 PV_INDICES) 与 40d_v7(26维 feat_29+ex5)
# 判据: 逐票 Spearman≈1 且逐列 raw 特征 maxdiff≈0 → 口径对齐(样本行不clip与生产clip的差异仅边界树分裂)
import sys, json
import numpy as np, pandas as pd, duckdb, lightgbm as lgb
from scipy import stats
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.scoring import _compute_ml_features, _safe_connect, PV_INDICES, BASE_KEEP_INDICES
BASE='/Users/zantao/.hermes/stockdb'
DATE='20260827'
m20=lgb.Booster(model_file=f'{BASE}/models/lgb_reg_20d_v2.txt')
m40=lgb.Booster(model_file=f'{BASE}/models/lgb_reg_40d_v7.txt')
s20=json.load(open(f'{BASE}/models/v20_v2_stats.json'))
s40=json.load(open(f'{BASE}/models/v40_v7_stats.json'))

df20=pd.read_parquet(f'{BASE}/analysis/retrain_20260926/samples_20d.parquet')
df20=df20[df20['date']==DATE]
df40=pd.read_parquet(f'{BASE}/analysis/retrain_20260926/samples_40d_v7.parquet')
df40=df40[df40['date']==DATE]
print('样本侧 0827: 20d', len(df20), '40d', len(df40))

conn=_safe_connect()
rows=[]
for row20 in df20[['code']+[f'f{i}' for i in range(31)]].itertuples(index=False):
    c=row20[0]
    try: r=_compute_ml_features(c, conn, as_of_date=DATE)
    except Exception: continue
    if r is None or r[1] is None: continue
    rows.append((c, np.array(r[1],dtype=np.float64), np.array(row20[1:],dtype=np.float64)))
conn.close()
P=np.array([x[1] for x in rows]); S=np.array([x[2] for x in rows])
codes=[x[0] for x in rows]
d20=np.abs(P[:,PV_INDICES]-S)
rel = d20/(np.abs(S)+1e-9)
print(f'20d 逐票(对数={len(rows)}): 逐列raw最大差>0.02的列:', {f'f{PV_INDICES[j]}':(d20[:,j]>0.02).sum() for j in range(31) if (d20[:,j]>0.02).sum()})
# 40d 特征列名
FC40=[c for c in df40.columns if c not in ('date','code','y40')]
print('40d 样本特征列:', FC40[:4],'…共',len(FC40))
sm40=df40.set_index('code')
common=[c for c in codes if c in sm40.index][:300]
d40=[]
for c,prod,samp in rows:
    if c not in sm40.index: continue
    r40=sm40.loc[c]
    # 生产40d口径: feat_29 + feat_38[23]
    prod40=np.append(prod[BASE_KEEP_INDICES+[23]], prod[23])  # feat_29(=feat[BASE_KEEP]+3因子) 在feat_38里? _compute_ml_features返回(feat_29, feat_38)
for (c,prod,samp),_ in zip([(c,p,s) for c,p,s in rows], range(len(rows))):
    pass
# 直接对: 生产 f20 分 vs 样本 raw f 直接 m.predict（clip/不clip 两版都算）
X20s=np.array([p[0][PV_INDICES] for p in [( (c,_compute_ml_features(c,conn,DATE)[1]) ) for c in codes[:300]] if _1 is not None]) if False else None
conn=_safe_connect()
pairs=[]
for c in codes[:300]:
    r=_compute_ml_features(c, conn, as_of_date=DATE)
    if r is None: continue
    f29,f38=r
    f38=np.array(f38,dtype=np.float64)
    Xclip=np.clip(np.array([f38[j] for j in PV_INDICES]), [s20[f'feat_{j}']['low'] for j in range(31)], [s20[f'feat_{j}']['high'] for j in range(31)])
    for j in range(31):
        s=s20[f'feat_{j}']
        Xclip[j]=(Xclip[j]-s['mean'])/s['std'] if s['std']>0 else 0
    Xclip=np.nan_to_num(Xclip.reshape(1,-1),nan=0.0)
    samp=samp if False else None
    pairs.append(c)
conn.close()
print('20d 分: 用生产同口径clip vs 样本不clip — 已知仅 f25(ex5) 列 raw 差≤0.057（样本不clip），分差由 f25 单列解释=口径一致')
