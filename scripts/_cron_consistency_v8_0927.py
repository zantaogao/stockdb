"""训练/推理一致性对账 v2（v8融合上线前）。
关键: 与线上 _compute_ml_features 完全同法取特征(含 its 60行截断), 只把 feat_38 换喂 v8 模型。
判据: 重算 pred 与样本表 y 无泄漏不可直接比, 改为两步:
  step A: 重算feat_38 与 样本特征向量(s10行) 的 Pearson 是否≈1 → 口径对齐
  step B: pred_v8 分布 sanity
"""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd, lightgbm as lgb
BASE = Path.home() / '.hermes/stockdb'
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(BASE/'scripts'))
from core.db import get_tushare_db
import core.scoring as sc
from feat_tushare import compute_features

OUT = BASE/'analysis/retrain_20260927_v8'
PV = [0,1,2,3,5,6,7,10,11,12,13,14,15,16,17,18,19,23,24,25,26,27,28,29,30,32,33,34,35,36,37]
BK = [0,1,2,3,4,5,6,7,8,9,11,12,13,14,15,18,19,20,21,22,23,24,25,26,28,29]
ASOF='20260728'
st10=json.load(open(OUT/'v10_v8_stats.json')); st40=json.load(open(OUT/'v40_v8_stats.json'))
m10=lgb.Booster(model_str=(OUT/'lgb_reg_10d_v8.txt').read_text())
m40=lgb.Booster(model_str=(OUT/'lgb_reg_40d_v8.txt').read_text())
def clipstd(X,st):
    X=np.asarray(X,float).copy()
    for j in range(X.shape[1]):
        s=st['feat_%d'%j]
        X[:,j]=(np.clip(X[:,j],s['low'],s['high'])-s['mean'])/s['std']
    return np.nan_to_num(X,nan=0.0)
s10=pd.read_parquet(OUT/'samples_10d.parquet'); s40=pd.read_parquet(OUT/'samples_40d.parquet')
s10['date']=s10.date.astype(str); s40['date']=s40.date.astype(str)
a10=s10[s10.date==ASOF].set_index('code'); a40=s40[s40.date==ASOF].set_index('code')
conn=get_tushare_db()
codes=sorted(set(a10.index)&set(a40.index))
np.random.seed(0); codes=list(np.random.choice(codes,300,replace=False))
rows=[]
for code in codes:
    try:
        got=sc._compute_ml_features(code,conn,as_of_date=ASOF)
    except Exception:
        continue
    if got is None: continue
    f29,f38=got
    if f38 is None: continue
    f38=[float(v) for v in f38]
    ts=code+'.SH' if code.startswith(('6','68')) else (code+'.BJ' if code.startswith('9') else code+'.SZ')
    fr=conn.execute("SELECT kdj_k,cci,rsi_12 FROM stk_factor WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1",[ts]).fetchone()
    fac=[float(v) if v is not None else 0.0 for v in fr] if fr else [0.0,0.0,0.0]
    v10=[f38[j] for j in PV]; v40=[f38[j] for j in BK]+fac
    p10=float(m10.predict(clipstd([v10],st10))[0]); p40=float(m40.predict(clipstd([v40],st40))[0])
    rows.append((code,p10,p40,v10,v40))
rb=pd.DataFrame(rows,columns=['code','p10','p40','v10','v40'])
# 口径对齐: 重算特征向量 vs 样本行向量
t10=pd.DataFrame({'code':a10.index,'x10':list(a10.iloc[:,31:].values)}).set_index('code')  # FC10=31列特征位于2..32
t10=pd.DataFrame({'code':a10.index,'x10':list(a10[['f%d'%j for j in range(31)]].values)}).set_index('code')
t40=pd.DataFrame({'code':a40.index,'x40':list(a40[['f%d'%j for j in range(26)]+['f31','f32','f33']].values)}).set_index('code')
mm=rb.set_index('code').join(t10).join(t40).dropna(subset=['x10','x40'])
c10=np.corrcoef(np.array([np.asarray(r,float) for r in mm.v10]).ravel(), np.array([np.asarray(r,float) for r in mm.x10]).ravel())[0,1]
c40=np.corrcoef(np.array([np.asarray(r,float) for r in mm.v40]).ravel(), np.array([np.asarray(r,float) for r in mm.x40]).ravel())[0,1]
print('票数', len(mm))
print('10d 线上重算特征 vs 样本特征 逐元素相关 %.6f'%c10)
print('40d 线上重算特征 vs 样本特征 逐元素相关 %.6f'%c40)
print('v8 pred分布: p10 mean%.3f std%.3f | p40 mean%.2f std%.2f'%(mm.p10.mean(),mm.p10.std(),mm.p40.mean(),mm.p40.std()))
conn.close()
