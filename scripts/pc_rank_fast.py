"""LambdaRank 40-day (no GTJA for speed)"""
import numpy as np, lightgbm as lgb, duckdb, json, time
from pathlib import Path
from scipy.stats import spearmanr

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
    print("LambdaRank 40d (no GTJA)",flush=True)
    
    with open(STATS_PATH) as f: ns=json.load(f)
    conn=duckdb.connect(str(DB),read_only=True)
    codes=[r[0] for r in conn.execute("SELECT DISTINCT stock_code FROM stock_daily ORDER BY stock_code").fetchall()]
    print(f"Stocks: {len(codes)}",flush=True)
    
    Xr,y=[],[]
    for ci,code in enumerate(codes):
        rows=conn.execute(f"SELECT close,COALESCE(change_pct,0),volume FROM stock_daily WHERE stock_code='{code}' AND date>='2020-01-01' ORDER BY date").fetchall()
        if len(rows)<FWIN+FWD+10: continue
        ca=[float(r[0]) for r in rows];aa=[float(r[2]) if r[2] else 0 for r in rows]
        ra=[float(r[1])/100 for r in rows]
        for i in range(FWIN,len(rows)-FWD):
            f=feat(ca[i-FWIN:i+1],aa[i-FWIN:i+1],ra[i-FWIN:i+1])
            for j in range(23):
                s=ns[f'feat_{j}']
                if s['std']>0:f[j]=(np.clip(f[j],s['low'],s['high'])-s['mean'])/s['std']
            f=np.nan_to_num(f,nan=0)
            fc=ca[i+FWD] if i+FWD<len(ca) else ca[-1];ret=(fc/ca[i]-1)*100
            Xr.append(f);y.append(ret)
        if (ci+1)%1000==0: print(f"  {ci+1}/{len(codes)}: {len(Xr)}",flush=True)
    conn.close()
    
    X=np.array(Xr,dtype=np.float32);y=np.array(y,dtype=np.float32)
    print(f"Samples: {len(X)} y mean={np.mean(y):+.1f}%",flush=True)
    
    n=len(X);idx=np.random.RandomState(42).permutation(n);nt=int(n*0.8)
    Xt,yt=X[idx[:nt]],y[idx[:nt]];Xv,yv=X[idx[nt:]],y[idx[nt:]]
    
    p33,p67=np.percentile(yt,[33,67])
    gt=np.zeros(nt,dtype=int);gt[yt>=p67]=2;gt[(yt>=p33)&(yt<p67)]=1
    gv=np.zeros(len(yv),dtype=int);gv[yv>=p67]=2;gv[(yv>=p33)&(yv<p67)]=1
    print(f"Groups: 0={sum(gt==0)} 1={sum(gt==1)} 2={sum(gt==2)}",flush=True)
    
    # LambdaRank requires query groups (max 10000/query). Split into 5K batches.
    np.random.seed(42)
    group_size = 5000
    
    # Train groups
    n_grps = nt // group_size
    tr_groups = [group_size] * n_grps
    if nt % group_size > 0: tr_groups.append(nt % group_size)
    
    # Val groups
    nv_grps = len(Xv) // group_size
    val_groups = [group_size] * nv_grps
    if len(Xv) % group_size > 0: val_groups.append(len(Xv) % group_size)
    
    print(f"Groups: train={len(tr_groups)} val={len(val_groups)} x ~{group_size}", flush=True)
    
    print("Training...", flush=True)
    dt = lgb.Dataset(Xt, label=gt, group=tr_groups)
    dv = lgb.Dataset(Xv, label=gv, group=val_groups, reference=dt)
    p={'objective':'lambdarank','metric':'ndcg','ndcg_eval_at':[3,5],
       'num_leaves':63,'learning_rate':0.03,'feature_fraction':0.8,
       'bagging_fraction':0.8,'bagging_freq':5,'min_data_in_leaf':100,
       'verbose':1,'num_threads':6,'max_depth':8,'device':'gpu','label_gain':[0,1,3]}
    m=lgb.train(p,dt,num_boost_round=500,valid_sets=[dt,dv],
        callbacks=[lgb.early_stopping(20),lgb.log_evaluation(50)])
    
    pv=m.predict(Xv);ic,_=spearmanr(pv,yv)
    a=np.array(list(zip(pv,yv)));a=a[a[:,0].argsort()]
    d10=len(a)//10;sp=np.mean(a[-d10:,1])-np.mean(a[:d10,1])
    print(f"LambdaRank: IC={ic:.4f} spread={sp:+.1f}% trees={m.num_trees()}",flush=True)
    
    l2p=BASE/'lgb_reg_40d.txt'
    if l2p.exists():
        m2=lgb.Booster(model_file=str(l2p));p2=m2.predict(Xv);ic2,_=spearmanr(p2,yv)
        print(f"L2:         IC={ic2:.4f} trees={m2.num_trees()}",flush=True)
        print(f"Delta: {ic-ic2:+.4f} {'LambdaRank WINS' if ic>ic2 else 'L2 WINS'}",flush=True)
    
    m.save_model(str(OUT_MODEL))
    print(f"Saved: {OUT_MODEL} ({time.time()-t0:.0f}s)",flush=True)

if __name__=='__main__': main()
