"""LambdaRank-only training (40-day, 3 groups) — reuse stats from L2 run"""
import numpy as np, lightgbm as lgb, duckdb, json, gzip, pickle, time
from pathlib import Path
from scipy.stats import spearmanr

BASE = Path('C:/Users/pumma/factor_lib')
DB = BASE / 'stock.db'
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'
STATS_PATH = BASE / 'v6_norm_stats_40d.json'
OUT_MODEL = BASE / 'lgb_rank_40d.txt'

FEAT_WIN, FWD_DAYS = 120, 40
GTJA_4 = ['gtja_006','gtja_083','gtja_177','gtja_184']

def compute_features(c_arr, a_arr, r_arr):
    c = np.array(c_arr); lc = c[-1]
    chg5=lc/c[-5]-1; chg10=lc/c[-10]-1; chg20=lc/c[-20]-1; chg60=lc/c[-60]-1; chg120=lc/c[0]-1
    ma5=np.mean(c[-5:]); ma10=np.mean(c[-10:]); ma20=np.mean(c[-20:]); ma60=np.mean(c[-60:])
    d5=lc/ma5-1; d10=lc/ma10-1; d20=lc/ma20-1; d60=lc/ma60-1; d120=lc/np.mean(c)-1
    b1=1 if ma5>ma10>ma20 else 0; b2=1 if ma20>ma60 else 0
    rn=np.max(c[-20:])-np.min(c[-20:]); rr=rn/np.min(c[-20:])*100 if np.min(c[-20:])>0 else 0
    std20=np.std(c[-20:])/np.mean(c[-20:])*100
    vols=np.array(a_arr[-20:]); vr=vols[-1]/np.mean(vols) if np.mean(vols)>0 else 1
    rl,rh=np.min(c[-20:]),np.max(c[-20:]); pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
    nh=1 if lc>rh*0.97 else 0; vpc=1 if chg5>0 and vr>1.2 else 0
    c3d = lc/c[-3]-1 if len(c)>=3 and c[-3]>0 else 0
    return np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
        b1,b2,rr,std20,vr,pos,nh,vpc,0,c3d,0.5,0.5,22.0], dtype=np.float32)

def main():
    t0 = time.time()
    print("LambdaRank 40-day Training", flush=True)
    print("=" * 60, flush=True)
    
    if not STATS_PATH.exists():
        print("ERROR: no stats file", flush=True); return
    with open(STATS_PATH) as f: norm_stats = json.load(f)
    
    print("Loading GTJA...", flush=True)
    with gzip.open(GTJA_PKL, 'rb') as f: gtja = pickle.load(f)
    
    conn = duckdb.connect(str(DB), read_only=True)
    stock_codes = [r[0] for r in conn.execute(
        "SELECT DISTINCT stock_code FROM stock_daily ORDER BY stock_code").fetchall()]
    print(f"Stocks: {len(stock_codes)}", flush=True)
    
    # Build data
    print("Building data...", flush=True)
    X_raw, y = [], []
    for ci, code in enumerate(stock_codes):
        rows = conn.execute(f"""SELECT date,close,COALESCE(change_pct,0),volume 
            FROM stock_daily WHERE stock_code='{code}' AND date>='2020-01-01' 
            ORDER BY date""").fetchall()
        if len(rows) < FEAT_WIN+FWD_DAYS+10: continue
        c_arr=[float(r[1]) for r in rows]; a_arr=[float(r[3]) if r[3] else 0 for r in rows]
        r_arr=[float(r[2])/100 for r in rows]; dates=[str(r[0])[:10] for r in rows]
        for i in range(FEAT_WIN, len(rows)-FWD_DAYS):
            feat=compute_features(c_arr[i-FEAT_WIN:i+1], a_arr[i-FEAT_WIN:i+1], r_arr[i-FEAT_WIN:i+1])
            gtja_v=[0.0]*4
            for gi, gn in enumerate(GTJA_4):
                if gn in gtja:
                    df=gtja[gn]; best=None
                    for d in reversed(sorted(df.index)):
                        if str(d)[:10]<=dates[i]: best=str(d)[:10]; break
                    if best and code in df.columns:
                        v=df.loc[best,code]; gtja_v[gi]=float(v) if not np.isnan(v) else 0.0
            feat=np.append(feat, np.array(gtja_v,dtype=np.float32))
            # Standardize
            for j in range(23):
                s=norm_stats[f'feat_{j}']
                if s['std']>0: feat[j]=(np.clip(feat[j],s['low'],s['high'])-s['mean'])/s['std']
            feat=np.nan_to_num(feat,nan=0)
            fc=c_arr[i+FWD_DAYS] if i+FWD_DAYS<len(c_arr) else c_arr[-1]
            ret=(fc/c_arr[i]-1)*100
            X_raw.append(feat); y.append(ret)
        if (ci+1)%500==0: print(f"  {ci+1}/{len(stock_codes)}: {len(X_raw)} samples", flush=True)
    
    conn.close()
    X=np.array(X_raw,dtype=np.float32); y=np.array(y,dtype=np.float32)
    print(f"Total: {len(X)} samples, y mean={np.mean(y):+.1f}% std={np.std(y):.1f}%", flush=True)
    
    # Split + groups
    n=len(X); idx=np.random.RandomState(42).permutation(n)
    n_train=int(n*0.8)
    X_train,y_train=X[idx[:n_train]],y[idx[:n_train]]
    X_val,y_val=X[idx[n_train:]],y[idx[n_train:]]
    
    p33,p67=np.percentile(y_train,[33,67])
    g_train=np.zeros(len(y_train),dtype=int)
    g_train[y_train>=p67]=2; g_train[(y_train>=p33)&(y_train<p67)]=1
    g_val=np.zeros(len(y_val),dtype=int)
    g_val[y_val>=p67]=2; g_val[(y_val>=p33)&(y_val<p67)]=1
    print(f"Groups train: 0={sum(g_train==0)} 1={sum(g_train==1)} 2={sum(g_train==2)}", flush=True)
    
    # Train
    print("\nTraining LambdaRank (GPU)...", flush=True)
    dtrain=lgb.Dataset(X_train,label=g_train,group=[len(X_train)])
    dval=lgb.Dataset(X_val,label=g_val,group=[len(X_val)],reference=dtrain)
    params={'objective':'lambdarank','metric':'ndcg','ndcg_eval_at':[3,5],
        'num_leaves':63,'learning_rate':0.03,'feature_fraction':0.8,
        'bagging_fraction':0.8,'bagging_freq':5,'min_data_in_leaf':100,
        'verbose':1,'num_threads':6,'max_depth':8,'device':'gpu',
        'label_gain':[0,1,3]}
    model=lgb.train(params,dtrain,num_boost_round=500,valid_sets=[dtrain,dval],
        callbacks=[lgb.early_stopping(20),lgb.log_evaluation(50)])
    
    # Eval vs continuous y
    pred_val=model.predict(X_val); ic,_=spearmanr(pred_val,y_val)
    arr=np.array(list(zip(pred_val,y_val))); arr=arr[arr[:,0].argsort()]
    d10=len(arr)//10; spread=np.mean(arr[-d10:,1])-np.mean(arr[:d10,1])
    print(f"\nLambdaRank Val: IC={ic:.4f} spread={spread:+.1f}% trees={model.num_trees()}", flush=True)
    
    # Compare with L2
    l2_path=BASE/'lgb_reg_40d.txt'
    if l2_path.exists():
        m2=lgb.Booster(model_file=str(l2_path))
        pred2=m2.predict(X_val); ic2,_=spearmanr(pred2,y_val)
        arr2=np.array(list(zip(pred2,y_val))); arr2=arr2[arr2[:,0].argsort()]
        d10_2=len(arr2)//10; spread2=np.mean(arr2[-d10_2:,1])-np.mean(arr2[:d10_2,1])
        print(f"L2        Val: IC={ic2:.4f} spread={spread2:+.1f}% trees={m2.num_trees()}", flush=True)
        print(f"\nDelta: IC {ic-ic2:+.4f} spread {spread-spread2:+.1f}%", flush=True)
        if ic>ic2: print("LambdaRank WINS", flush=True)
        else: print("L2 WINS", flush=True)
    
    model.save_model(str(OUT_MODEL))
    print(f"\nSaved: {OUT_MODEL}", flush=True)
    print(f"Time: {(time.time()-t0)/60:.0f} min", flush=True)

if __name__=='__main__':
    main()
