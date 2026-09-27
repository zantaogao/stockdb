import sys, json
from pathlib import Path
import numpy as np, pandas as pd, lightgbm as lgb
BASE=Path.home()/'.hermes/stockdb'; sys.path.insert(0,str(BASE)); sys.path.insert(0,str(BASE/'scripts'))
import core.scoring as sc
from core.db import get_tushare_db
from feat_tushare import compute_features, apply_forward_adjust, load_index_data
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
codes=list(np.random.RandomState(1).choice(sorted(a40.index),300,replace=False))
rows=[]
for c in codes:
    ts=c+'.SH' if c.startswith(('6','68')) else (c+'.BJ' if c.startswith('9') else c+'.SZ')
    drows=conn.execute("SELECT trade_date,close,open,high,low,COALESCE(pct_chg,0),vol FROM daily WHERE ts_code=? ORDER BY trade_date",[ts]).fetchall()
    dts=[str(r[0]) for r in drows]
    if ASOF not in dts: continue
    k=dts.index(ASOF)
    if k<60: continue
    closes=[float(r[1]) for r in drows]; highs=[float(r[3]) for r in drows]; lows=[float(r[4]) for r in drows]
    pcts=[float(r[5])/100 for r in drows]; vols=[float(r[6]) for r in drows]
    adj=conn.execute("SELECT trade_date,adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date",[ts]).fetchall()
    ac,ah,al=apply_forward_adjust(closes,highs,lows,adj)
    vb=conn.execute("SELECT pe_ttm,pb,total_mv FROM daily_basic WHERE ts_code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 1",[ts,ASOF]).fetchone()
    vd={}
    if vb:
        pe,pb,mv=vb
        if pe and float(pe)>0: vd['ep']=1/float(pe)
        if pb and float(pb)>0: vd['bp']=1/float(pb)
        if mv and float(mv)>0: vd['ln_cap']=np.log(float(mv))
    # ex窗口: 个股日历idx_closes(与score_stock 0926修复后逻辑一致)
    idx=load_index_data(); bi=None
    from feat_tushare import get_board_index
    bi=get_board_index(c); info=idx.get(bi); idx_closes=None
    if info:
        import bisect
        dn=[dd.replace('-','') for dd in info['dates']]
        ip=bisect.bisect_right(dn,ASOF)-1
        if ip>=20: idx_closes={info['dates'][j]:info['dict'][info['dates'][j]] for j in range(ip+1)}
    win=[f'{x[:4]}-{x[4:6]}-{x[6:8]}' for x in dts[k-60:k+1]]
    f38=compute_features(ac[k-60:k+1],ah[k-60:k+1],al[k-60:k+1],vols[k-60:k+1],pcts[k-60:k+1],idx_closes,vd,dates=win)
    if f38 is None or len(list(f38))!=38: continue
    f38=[float(v) for v in f38]
    fr=conn.execute("SELECT kdj_k,cci,rsi_12 FROM stk_factor WHERE ts_code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 1",[ts,ASOF]).fetchone()
    fac=[float(v) if v is not None else 0.0 for v in fr] if fr else [0.,0.,0.]
    f40=[f38[j] for j in BK]+fac
    p_exact=float(m40.predict(clipstd([f40]))[0])
    rows.append((c,p_exact))
rb=pd.DataFrame(rows,columns=['code','p_exact']).set_index('code')
mm=a40.join(rb).dropna(subset=['p_exact'])
direct=m40.predict(clipstd(mm[['f%d'%j for j in range(26)]+['f31','f32','f33']].to_numpy(float)))
print('票数',len(mm))
print('样本精确特征pred vs 全量重算pred: corr %.6f  maxdiff %.4f'%(np.corrcoef(direct,mm.p_exact)[0,1], np.abs(direct-mm.p_exact.to_numpy()).max()))
conn.close()
