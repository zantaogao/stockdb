"""终验: score_stock(as_of=20260728) vs 样本行直接predict(新v8模型).
同 conn(默认链路)、同 val/fac 查询逻辑 → 差异只应来自 f4/f9(feat_38[9]/[11]即chg60 vs chg120?) 的5日回看.
判据: reg40 与样本直pred 相关应=1.0 或 maxdiff<0.01(clip+std后5日差被压缩).
"""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd, lightgbm as lgb
BASE = Path.home()/'.hermes/stockdb'
sys.path.insert(0, str(BASE))
import core.scoring as sc
from core.db import get_tushare_db

OUT = BASE/'analysis/retrain_20260927_v8'
ASOF='20260728'
st40=json.load(open(OUT/'v40_v8_stats.json'))
m40=lgb.Booster(model_str=(OUT/'lgb_reg_40d_v8.txt').read_text())
s40=pd.read_parquet(OUT/'samples_40d.parquet'); s40['date']=s40.date.astype(str)
a40=s40[s40.date==ASOF]
def clipstd(X):
    X=np.asarray(X,float).copy()
    for j in range(X.shape[1]):
        s=st40['feat_%d'%j]
        X[:,j]=(np.clip(X[:,j],s['low'],s['high'])-s['mean'])/s['std']
    return np.nan_to_num(X,nan=0.0)
pred_direct=m40.predict(clipstd(a40[['f%d'%j for j in range(26)]+['f31','f32','f33']].to_numpy(float)))
a=pd.DataFrame({'code':a40.code,'pred_direct':pred_direct}).set_index('code')
conn=get_tushare_db()
codes=list(np.random.RandomState(1).choice(sorted(a.index),400,replace=False))
rows=[]
for c in codes:
    try:
        got=sc.score_stock(c, conn=conn, as_of_date=ASOF)
        if got is None: continue
        rows.append((c, got['reg40_pred']))
    except Exception as e:
        continue
rb=pd.DataFrame(rows,columns=['code','score_stock']).set_index('code')
mm=a.join(rb).dropna()
mm['score_stock']=mm.score_stock.astype(float)
print('票数',len(mm))
print('corr %.6f  maxdiff %.4f  mean|diff| %.4f'%(mm.pred_direct.corr(mm.score_stock), (mm.pred_direct-mm.score_stock).abs().max(), (mm.pred_direct-mm.score_stock).abs().mean()))
print(mm.reindex((mm.pred_direct-mm.score_stock).abs().sort_values(ascending=False).index).head(3))
conn.close()
