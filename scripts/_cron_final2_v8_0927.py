import sys, json
from pathlib import Path
import numpy as np, pandas as pd, lightgbm as lgb
BASE=Path.home()/'.hermes/stockdb'; sys.path.insert(0,str(BASE))
import core.scoring as sc
from core.db import get_tushare_db
OUT=BASE/'analysis/retrain_20260927_v8'
ASOF='20260728'
st40=json.load(open(OUT/'v40_v8_stats.json')); m40=lgb.Booster(model_str=(OUT/'lgb_reg_40d_v8.txt').read_text())
s40=pd.read_parquet(OUT/'samples_40d.parquet'); s40['date']=s40.date.astype(str)
a40=s40[s40.date==ASOF].set_index('code')
BK=[0,1,2,3,4,5,6,7,8,9,11,12,13,14,15,18,19,20,21,22,23,24,25,26,28,29]
def clipstd(X):
    X=np.asarray(X,float).copy()
    for j in range(X.shape[1]):
        s=st40['feat_%d'%j]; X[:,j]=(np.clip(X[:,j],s['low'],s['high'])-s['mean'])/s['std']
    return np.nan_to_num(X,nan=0.0)
conn=get_tushare_db()
codes=list(np.random.RandomState(1).choice(sorted(a40.index),200,replace=False))
rows=[]
for c in codes:
    got=sc._compute_ml_features(c,conn,as_of_date=ASOF)
    if got is None: continue
    _,f38=got
    if f38 is None: continue
    f38=[float(v) for v in f38]
    ts=c+'.SH' if c.startswith(('6','68')) else (c+'.BJ' if c.startswith('9') else c+'.SZ')
    fr=conn.execute("SELECT kdj_k,cci,rsi_12 FROM stk_factor WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1",[ts]).fetchone()
    fac=[float(v) if v is not None else 0.0 for v in fr] if fr else [0.,0.,0.]
    f40=[f38[j] for j in BK]+fac
    p_exact=float(m40.predict(clipstd([f40]))[0]); p_round=float(np.round(p_exact,1))
    rows.append((c,p_exact,p_round))
rb=pd.DataFrame(rows,columns=['code','p_exact','p_round']).set_index('code')
print('票数',len(rb))
print('pred分布: exact mean%.3f std%.3f | round mean%.3f std%.3f'%(rb.p_exact.mean(),rb.p_exact.std(),rb.p_round.mean(),rb.p_round.std()))
print('exact vs round 最大差 %.3f'%(rb.p_exact-rb.p_round).abs().max())
conn.close()
