"""PC Runner — 40-day L2 → LambdaRank sequential training + comparison"""
import os, json, gzip, pickle, time, numpy as np
import lightgbm as lgb
import duckdb
from pathlib import Path

BASE = Path('C:/Users/pumma/factor_lib')
DB = BASE / 'stock.db'
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'

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
        b1,b2,rr,std20,vr,pos,nh,vpc,0,c3d,
        0.5,0.5,22.0], dtype=np.float32)

def build_data(conn, stock_codes, gtja):
    X_raw, y = [], []
    for ci, code in enumerate(stock_codes):
        rows = conn.execute(f"""SELECT date,close,COALESCE(change_pct,0),volume 
            FROM stock_daily WHERE stock_code='{code}' AND date>='2020-01-01' ORDER BY date""").fetchall()
        if len(rows) < FEAT_WIN+FWD_DAYS+10: continue
        c_arr=[float(r[1]) for r in rows]; a_arr=[float(r[3]) if r[3] else 0 for r in rows]
        r_arr=[float(r[2])/100 for r in rows]; dates=[str(r[0])[:10] for r in rows]
        for i in range(FEAT_WIN, len(rows)-FWD_DAYS):
            feat=compute_features(c_arr[i-FEAT_WIN:i+1], a_arr[i-FEAT_WIN:i+1], r_arr[i-FEAT_WIN:i+1])
            gtja_v=[]
            for gn in GTJA_4:
                if gn in gtja:
                    df=gtja[gn]; best=None
                    for d in reversed(sorted(df.index)):
                        if str(d)[:10]<=dates[i]: best=str(d)[:10]; break
                    gtja_v.append(float(df.loc[best,code]) if best and code in df.columns and not np.isnan(df.loc[best,code]) else 0.0)
                else: gtja_v.append(0.0)
            feat=np.append(feat, np.array(gtja_v,dtype=np.float32))
            fc=c_arr[i+FWD_DAYS] if i+FWD_DAYS<len(c_arr) else c_arr[-1]
            ret=(fc/c_arr[i]-1)*100
            X_raw.append(feat); y.append(ret)
        if (ci+1)%500==0: print(f"  {ci+1}/{len(stock_codes)} stocks, {len(X_raw)} samples")
    return np.array(X_raw,dtype=np.float32), np.array(y,dtype=np.float32)

def standardize(X, stats):
    Xs=X.copy()
    for j in range(23):
        s=stats[f'feat_{j}']
        if s['std']>0: Xs[:,j]=np.clip(Xs[:,j],s['low'],s['high']); Xs[:,j]=(Xs[:,j]-s['mean'])/s['std']
    return np.nan_to_num(Xs,nan=0.0)

def compute_stats(X):
    stats={}
    for j in range(23):
        v=X[:,j]; valid=v[~np.isnan(v)]
        stats[f'feat_{j}']={'mean':float(np.mean(valid)),'std':float(np.std(valid)),
            'low':float(np.percentile(valid,1)),'high':float(np.percentile(valid,99))}
    return stats

def eval_model(model, X, y, label):
    from scipy import stats as sp
    pred=model.predict(X); ic,_=sp.spearmanr(pred,y)
    arr=np.array(list(zip(pred,y))); arr=arr[arr[:,0].argsort()]
    d10=len(arr)//10; spread=np.mean(arr[-d10:,1])-np.mean(arr[:d10,1])
    print(f"  {label}: IC={ic:.4f} spread={spread:+.1f}%")
    return ic, spread

def train_l2(X_train, y_train, X_val, y_val):
    print("\n" + "="*60)
    print("Stage 1: L2 Regression (40-day)")
    print("="*60)
    dtrain=lgb.Dataset(X_train,y_train); dval=lgb.Dataset(X_val,y_val,reference=dtrain)
    params={'objective':'regression','metric':'l2','num_leaves':63,'learning_rate':0.03,
        'feature_fraction':0.8,'bagging_fraction':0.8,'bagging_freq':5,
        'min_data_in_leaf':100,'verbose':1,'num_threads':6,'max_depth':8,'device':'gpu'}
    model=lgb.train(params,dtrain,num_boost_round=500,valid_sets=[dtrain,dval],
        callbacks=[lgb.early_stopping(20),lgb.log_evaluation(50)])
    ic_train,spread_train=eval_model(model,X_train,y_train,'train')
    ic_val,spread_val=eval_model(model,X_val,y_val,'val')
    model.save_model(str(BASE/'lgb_reg_40d.txt'))
    return model, ic_val, spread_val

def train_lambdarank(X_train, y_train, X_val, y_val):
    print("\n" + "="*60)
    print("Stage 2: LambdaRank (40-day, 3 groups)")
    print("="*60)
    # 将连续收益转为3组: bottom 33%, middle 33%, top 33%
    def make_groups(y_arr):
        p33,p67=np.percentile(y_arr,[33,67])
        g=np.zeros(len(y_arr)); g[y_arr>=p67]=2; g[(y_arr>=p33)&(y_arr<p67)]=1
        return g.astype(int)
    
    g_train=make_groups(y_train); g_val=make_groups(y_val)
    print(f"  Groups: 0={sum(g_train==0)} 1={sum(g_train==1)} 2={sum(g_train==2)}")
    
    dtrain=lgb.Dataset(X_train,label=g_train,group=[len(X_train)])
    dval=lgb.Dataset(X_val,label=g_val,group=[len(X_val)],reference=dtrain)
    
    params={'objective':'lambdarank','metric':'ndcg','ndcg_eval_at':[3,5,10],
        'num_leaves':63,'learning_rate':0.03,'feature_fraction':0.8,
        'bagging_fraction':0.8,'bagging_freq':5,'min_data_in_leaf':100,
        'verbose':1,'num_threads':6,'max_depth':8,'device':'gpu',
        'label_gain':[0,1,3]}  # group 2 weighted 3x for NDCG
    model=lgb.train(params,dtrain,num_boost_round=500,valid_sets=[dtrain,dval],
        callbacks=[lgb.early_stopping(20),lgb.log_evaluation(50)])
    
    # LambdaRank outputs ranking scores, evaluate vs original y for IC comparison
    ic_train,spread_train=eval_model(model,X_train,y_train,'train')
    ic_val,spread_val=eval_model(model,X_val,y_val,'val')
    model.save_model(str(BASE/'lgb_rank_40d.txt'))
    return model, ic_val, spread_val

def main():
    t0=time.time()
    print("PC Runner: L2 -> LambdaRank (40-day)")
    print("="*60)
    
    print("Loading GTJA...")
    with gzip.open(GTJA_PKL,'rb') as f: gtja=pickle.load(f)
    conn=duckdb.connect(str(DB),read_only=True)
    stock_codes=[r[0] for r in conn.execute("SELECT DISTINCT stock_code FROM stock_daily ORDER BY stock_code").fetchall()]
    print(f"Stocks: {len(stock_codes)}")
    
    print("\nBuilding data...")
    X_raw,y=build_data(conn,stock_codes,gtja)
    conn.close()
    print(f"Total: {len(X_raw)} samples, label mean={np.mean(y):+.2f}% std={np.std(y):.2f}%")
    
    # Stats & split
    stats=compute_stats(X_raw)
    X=standardize(X_raw,stats)
    with open(BASE/'v6_norm_stats_40d.json','w') as f: json.dump(stats,f)
    
    n=len(X); idx=np.random.RandomState(42).permutation(n)
    n_train=int(n*0.8)
    X_train,y_train=X[idx[:n_train]],y[idx[:n_train]]
    X_val,y_val=X[idx[n_train:]],y[idx[n_train:]]
    print(f"Train: {n_train}, Val: {len(X_val)}")
    
    # Stage 1: L2
    _, l2_ic, l2_spread = train_l2(X_train, y_train, X_val, y_val)
    
    # Stage 2: LambdaRank  
    _, lr_ic, lr_spread = train_lambdarank(X_train, y_train, X_val, y_val)
    
    # Comparison
    print("\n" + "="*60)
    print("Comparison: L2 vs LambdaRank")
    print("="*60)
    print(f"{'Model':<15} {'Val IC':>8} {'Spread':>8}")
    print(f"{'L2 (reg)':<15} {l2_ic:>+8.4f} {l2_spread:>+7.1f}%")
    print(f"{'LambdaRank':<15} {lr_ic:>+8.4f} {lr_spread:>+7.1f}%")
    
    if lr_ic > l2_ic:
        print(f"\nLambdaRank wins: IC {lr_ic-l2_ic:+.4f} better")
    else:
        print(f"\nL2 wins: IC {l2_ic-lr_ic:+.4f} better")
    
    print(f"\nTotal time: {(time.time()-t0)/60:.0f} min")

if __name__=='__main__':
    main()
