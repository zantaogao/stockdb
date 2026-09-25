"""LambdaRank 40-day — date-based query groups"""
import numpy as np, lightgbm as lgb, duckdb, json, time
from pathlib import Path
from scipy.stats import spearmanr
from collections import defaultdict

BASE = Path('C:/Users/pumma/factor_lib')
DB = BASE / 'stock.db'
STATS_PATH = BASE / 'v6_norm_stats_40d.json'
OUT_MODEL = BASE / 'lgb_rank_40d.txt'

FWIN, FWD = 120, 40

def feat(c,a,r):
    c=np.array(c);lc=c[-1]
    chg5=lc/c[-5]-1;chg10=lc/c[-10]-1;chg20=lc/c[-20]-1;chg60=lc/c[-60]-1;chg120=lc/c[0]-1
    ma5=np.mean(c[-5:]);ma10=np.mean(c[-10:]);ma20=np.mean(c[-20:]);ma60=np.mean(c[-60:])
    d5=lc/ma5-1;d10=lc/ma10-1;d20=lc/ma20-1;d60=lc/ma60-1;d120=lc/np.mean(c)-1
    b1=1 if ma5>ma10>ma20 else 0;b2=1 if ma20>ma60 else 0
    rn=np.max(c[-20:])-np.min(c[-20:]);rr=rn/np.min(c[-20:])*100 if np.min(c[-20:])>0 else 0
    std20=np.std(c[-20:])/np.mean(c[-20:])*100
    vv=np.array(a[-20:]);vr=vv[-1]/np.mean(vv) if np.mean(vv)>0 else 1
    rl,rh=np.min(c[-20:]),np.max(c[-20:]);pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
    nh=1 if lc>rh*0.97 else 0;vpc=1 if chg5>0 and vr>1.2 else 0
    c3d=lc/c[-3]-1 if len(c)>=3 and c[-3]>0 else 0
    f=np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
        b1,b2,rr,std20,vr,pos,nh,vpc,0,c3d,0.5,0.5,22.0],dtype=np.float32)
    return np.append(f,np.zeros(4,dtype=np.float32))

def main():
    t0=time.time()
    print("LambdaRank 40d (date-grouped)",flush=True)
    
    with open(STATS_PATH) as f: ns=json.load(f)
    conn=duckdb.connect(str(DB),read_only=True)
    codes=[r[0] for r in conn.execute("SELECT DISTINCT stock_code FROM stock_daily ORDER BY stock_code").fetchall()]
    print(f"Stocks: {len(codes)}",flush=True)
    
    # Build data with date tracking
    date_samples = defaultdict(list)  # date -> [(features, return)]
    for ci,code in enumerate(codes):
        rows=conn.execute(f"SELECT date,close,COALESCE(change_pct,0),volume FROM stock_daily WHERE stock_code='{code}' AND date>='2020-01-01' ORDER BY date").fetchall()
        if len(rows)<FWIN+FWD+10: continue
        ca=[float(r[1]) for r in rows];aa=[float(r[2]) if r[2] else 0 for r in rows]
        ra=[float(r[1])/100 for r in rows];dates=[str(r[0])[:10] for r in rows]
        for i in range(FWIN,len(rows)-FWD):
            f=feat(ca[i-FWIN:i+1],aa[i-FWIN:i+1],ra[i-FWIN:i+1])
            for j in range(23):
                s=ns[f'feat_{j}']
                if s['std']>0:f[j]=(np.clip(f[j],s['low'],s['high'])-s['mean'])/s['std']
            f=np.nan_to_num(f,nan=0)
            fc=ca[i+FWD] if i+FWD<len(ca) else ca[-1];ret=(fc/ca[i]-1)*100
            date_samples[dates[i]].append((f,ret))
        if (ci+1)%1000==0: print(f"  {ci+1}/{len(codes)}: {sum(len(v) for v in date_samples.values())}",flush=True)
    conn.close()
    
    total=sum(len(v) for v in date_samples.values())
    print(f"Samples: {total} across {len(date_samples)} dates",flush=True)
    
    # Save data to disk for faster retries
    import pickle
    with open(BASE/'rank_data.pkl','wb') as f:
        pickle.dump(date_samples,f)
    print("Data saved to rank_data.pkl",flush=True)
    
    # Filter dates with enough samples
    valid_dates=[d for d,v in date_samples.items() if len(v)>=5]
    print(f"Valid dates (>5 stocks): {len(valid_dates)}",flush=True)
    
    # Build flat arrays + groups
    X_all,y_all,groups=[],[],[]
    for d in valid_dates:
        samples=date_samples[d]
        for f,r in samples: X_all.append(f);y_all.append(r)
        groups.append(len(samples))
    
    X=np.array(X_all,dtype=np.float32);y=np.array(y_all,dtype=np.float32)
    groups=np.array(groups,dtype=np.int32)
    
    # Chronological split: last 20% of dates for validation
    n_dates=len(groups)
    n_train_dates=int(n_dates*0.8)
    train_end_idx=sum(groups[:n_train_dates])
    
    Xt,yt=X[:train_end_idx],y[:train_end_idx]
    Xv,yv_=X[train_end_idx:],y[train_end_idx:]
    tr_groups=list(groups[:n_train_dates])
    val_groups=list(groups[n_train_dates:])
    
    # Labels: 3 groups
    p33,p67=np.percentile(yt,[33,67])
    gt=np.zeros(len(yt),dtype=int);gt[yt>=p67]=2;gt[(yt>=p33)&(yt<p67)]=1
    gv=np.zeros(len(yv_),dtype=int);gv[yv_>=p67]=2;gv[(yv_>=p33)&(yv_<p67)]=1
    
    # Cap groups at 10000
    def cap_groups(g, maxg=10000):
        out=[]
        for sz in g:
            while sz>maxg: out.append(maxg);sz-=maxg
            if sz>0: out.append(sz)
        return out
    tr_groups=cap_groups(tr_groups)
    val_groups=cap_groups(val_groups)
    
    print(f"Train: {len(Xt)} ({len(tr_groups)} groups) Val: {len(Xv)} ({len(val_groups)} groups)",flush=True)
    
    print("Training...",flush=True)
    dt=lgb.Dataset(Xt,label=gt,group=tr_groups)
    dv=lgb.Dataset(Xv,label=gv,group=val_groups,reference=dt)
    p={'objective':'lambdarank','metric':'ndcg','ndcg_eval_at':[3,5],
       'num_leaves':63,'learning_rate':0.03,'feature_fraction':0.8,
       'bagging_fraction':0.8,'bagging_freq':5,'min_data_in_leaf':100,
       'verbose':1,'num_threads':6,'max_depth':8,'device':'gpu','label_gain':[0,1,3]}
    m=lgb.train(p,dt,num_boost_round=500,valid_sets=[dt,dv],
        callbacks=[lgb.early_stopping(20),lgb.log_evaluation(50)])
    
    pv=m.predict(Xv);ic,_=spearmanr(pv,yv_)
    a=np.array(list(zip(pv,yv_)));a=a[a[:,0].argsort()]
    d10=len(a)//10;sp=np.mean(a[-d10:,1])-np.mean(a[:d10,1])
    print(f"LambdaRank: IC={ic:.4f} spread={sp:+.1f}% trees={m.num_trees()}",flush=True)
    
    l2p=BASE/'lgb_reg_40d.txt'
    if l2p.exists():
        m2=lgb.Booster(model_file=str(l2p))
        # Re-standardize for L2 stats
        # Actually L2 model uses same stats, just predict
        p2=m2.predict(Xv);ic2,_=spearmanr(p2,yv_)
        print(f"L2:         IC={ic2:.4f} trees={m2.num_trees()}",flush=True)
        print(f"Delta: {ic-ic2:+.4f} {'LambdaRank WINS' if ic>ic2 else 'L2 WINS'}",flush=True)
    
    m.save_model(str(OUT_MODEL))
    print(f"Saved ({time.time()-t0:.0f}s)",flush=True)

if __name__=='__main__': main()
