"""Quick IC check for lgb_reg_40d.txt + LambdaRank-only training"""
import numpy as np, lightgbm as lgb, duckdb, json, gzip, pickle, time, sys
from pathlib import Path
from scipy.stats import spearmanr

BASE = Path('C:/Users/pumma/factor_lib')
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'
MODEL_L2 = BASE / 'lgb_reg_40d.txt'
MODEL_LR = BASE / 'lgb_rank_40d.txt'
STATS_PATH = BASE / 'v6_norm_stats_40d.json'

def main():
    t0 = time.time()
    
    # Check if stats exist (from runner)
    if not STATS_PATH.exists():
        print("No stats file, need full run")
        return
    
    with open(STATS_PATH) as f: norm_stats = json.load(f)
    with gzip.open(GTJA_PKL,'rb') as f: gtja = pickle.load(f)
    
    conn = duckdb.connect(str(BASE/'stock.db'), read_only=True)
    codes = [r[0] for r in conn.execute("SELECT DISTINCT stock_code FROM stock_daily LIMIT 300").fetchall()]
    
    # L2 IC check
    if MODEL_L2.exists():
        m2 = lgb.Booster(model_file=str(MODEL_L2))
        print(f"L2 model: {m2.num_trees()}t {m2.num_feature()}d", flush=True)
    
    # Quick data
    print("Building eval data...", flush=True)
    X, y = [], []
    for code in codes:
        rows = conn.execute(f"""SELECT close,COALESCE(change_pct,0),volume FROM stock_daily 
            WHERE stock_code='{code}' AND date>='2025-01-01' ORDER BY date""").fetchall()
        if len(rows) < 160: continue
        c=[float(r[0]) for r in rows]; a=[float(r[2]) if r[2] else 0 for r in rows]
        r_arr=[float(r[1])/100 for r in rows]
        for i in range(120, len(rows)-40):
            lc=c[i]; chg5=lc/c[i-5]-1; chg10=lc/c[i-10]-1; chg20=lc/c[i-20]-1; chg60=lc/c[i-60]-1; chg120=lc/c[i-120+1]-1
            ma5=np.mean(c[i-4:i+1]); ma10=np.mean(c[i-9:i+1]); ma20=np.mean(c[i-19:i+1]); ma60=np.mean(c[i-59:i+1])
            d5=lc/ma5-1; d10=lc/ma10-1; d20=lc/ma20-1; d60=lc/ma60-1; d120=lc/np.mean(c[:i+1])-1
            b1=1 if ma5>ma10>ma20 else 0; b2=1 if ma20>ma60 else 0
            rn=np.max(c[i-19:i+1])-np.min(c[i-19:i+1]); rr=rn/np.min(c[i-19:i+1])*100 if np.min(c[i-19:i+1])>0 else 0
            std20=np.std(c[i-19:i+1])/np.mean(c[i-19:i+1])*100
            vv=a[i-19:i+1]; vr=vv[-1]/np.mean(vv) if np.mean(vv)>0 else 1
            rl,rh=np.min(c[i-19:i+1]),np.max(c[i-19:i+1]); pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
            nh=1 if lc>rh*0.97 else 0; vpc=1 if chg5>0 and vr>1.2 else 0
            c3d=lc/c[i-3]-1 if i>=3 and c[i-3]>0 else 0
            feat=np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
                b1,b2,rr,std20,vr,pos,nh,vpc,0,c3d,0.5,0.5,22.0],dtype=np.float32)
            # GTJA
            gtja_v=[0,0,0,0]
            feat=np.append(feat, np.array(gtja_v,dtype=np.float32))
            # standardize
            for j in range(23):
                s=norm_stats.get(f'feat_{j}',{})
                if s.get('std',0)>0: feat[j]=(np.clip(feat[j],s['low'],s['high'])-s['mean'])/s['std']
            feat=np.nan_to_num(feat,nan=0)
            fc=c[i+40] if i+40<len(c) else c[-1]; ret=(fc/lc-1)*100
            X.append(feat); y.append(ret)
    
    X=np.array(X,dtype=np.float32); y=np.array(y,dtype=np.float32)
    print(f"Eval samples: {len(X)} label mean={np.mean(y):+.1f}%", flush=True)
    
    if MODEL_L2.exists():
        pred=m2.predict(X); ic,_=spearmanr(pred,y)
        arr=np.array(list(zip(pred,y))); arr=arr[arr[:,0].argsort()]
        d10=len(arr)//10; spread=np.mean(arr[-d10:,1])-np.mean(arr[:d10,1])
        print(f"L2 (40d): IC={ic:.4f} spread={spread:+.1f}% n={len(X)}", flush=True)
    
    conn.close()
    print(f"Done: {time.time()-t0:.0f}s", flush=True)

if __name__=='__main__':
    main()
