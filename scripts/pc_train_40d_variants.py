"""LightGBM 40d回归 — 多种损失函数对比
一次性加载数据，训练3个变种：
  A. Huber 损失 (huber_delta=1.0)
  B. 标签截断±15% + MSE
  C. MAE 损失

时间切分：train < 2025-01-01, val >= 2025-01-01
特征：23基础(含真实估值) + 4GTJA = 27维
"""
import os, json, gzip, pickle, time, sys
import numpy as np
import lightgbm as lgb
import duckdb
from pathlib import Path
from scipy import stats

BASE = Path('C:/Users/pumma/factor_lib')
DB = BASE / 'stock.db'
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'
OUT_DIR = BASE

sys.stdout.reconfigure(line_buffering=True)

FEAT_WIN = 120
FWD_DAYS = 40
SPLIT_DATE = '2025-01-01'
GTJA_4 = ['gtja_006', 'gtja_083', 'gtja_177', 'gtja_184']

def compute_features(c_arr, a_arr, r_arr, v):
    c = np.array(c_arr); lc = c[-1]
    chg5=lc/c[-5]-1;chg10=lc/c[-10]-1;chg20=lc/c[-20]-1;chg60=lc/c[-60]-1;chg120=lc/c[0]-1
    m5=np.mean(c[-5:]);m10=np.mean(c[-10:]);m20=np.mean(c[-20:]);m60=np.mean(c[-60:])
    d5=lc/m5-1;d10=lc/m10-1;d20=lc/m20-1;d60=lc/m60-1;d120=lc/np.mean(c)-1
    b1=1 if m5>m10>m20 else 0;b2=1 if m20>m60 else 0
    rn=np.max(c[-20:])-np.min(c[-20:]);rr=rn/np.min(c[-20:])*100 if np.min(c[-20:])>0 else 0
    std20=np.std(c[-20:])/np.mean(c[-20:])*100
    vols=np.array(a_arr[-20:]);vr=vols[-1]/np.mean(vols) if np.mean(vols)>0 else 1
    rl,rh=np.min(c[-20:]),np.max(c[-20:]);pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
    nh=1 if lc>rh*0.97 else 0;vpc=1 if chg5>0 and vr>1.2 else 0
    c1d=r_arr[-1] if len(r_arr)>0 else 0;c3d=lc/c[-3]-1 if len(c)>=3 else 0
    ep=v.get('ep',0.5);bp=v.get('bp',0.5);ln_cap=v.get('ln_cap',22.0)
    return np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
        b1,b2,rr,std20,vr,pos,nh,vpc,c1d,c3d,ep,bp,ln_cap], dtype=np.float32)

def build_gtja_lookup(gd, gn):
    if gn not in gd: return None, None, None
    df=gd[gn]; dates=[str(d)[:10] for d in sorted(df.index)]
    return dates, df, None

def gtja_val(code, ds, lu):
    import bisect
    dates,df,_=lu
    if dates is None: return 0.0
    idx=bisect.bisect_right(dates,ds[:10])-1
    if idx>=0:
        d=dates[idx]
        if code in df.columns:
            x=df.loc[d,code]
            return float(x) if not np.isnan(x) else 0.0
    return 0.0

t0=time.time()
print("Loading GTJA...")
with gzip.open(GTJA_PKL,'rb') as f: gd=pickle.load(f)
luks={gn:build_gtja_lookup(gd,gn) for gn in GTJA_4}

print("Loading DB...")
con=duckdb.connect(str(DB),read_only=True)

print("Loading valuation...")
vd={}
for code,dt,pe,pb,mv in con.execute("SELECT stock_code,date,pe_ttm,pb,total_mv FROM stock_valuation ORDER BY stock_code,date").fetchall():
    ds=str(dt)[:10];d={}
    if pe and pe>0: d['ep']=1.0/float(pe)
    if pb and pb>0: d['bp']=1.0/float(pb)
    if mv and mv>0: d['ln_cap']=np.log(float(mv))
    if d: vd[(code,ds)]=d
print(f"  {len(vd)} entries")

codes=[r[0] for r in con.execute("SELECT DISTINCT stock_code FROM stock_daily WHERE date>='2020-01-01' ORDER BY stock_code").fetchall()]
print(f"Stocks: {len(codes)}")

X_list,y_list,dl=[],[],[]
for ci,code in enumerate(codes):
    rows=con.execute(f"SELECT date,close,COALESCE(change_pct,0),volume FROM stock_daily WHERE stock_code='{code}' AND date>='2020-01-01' ORDER BY date").fetchall()
    if len(rows)<FEAT_WIN+FWD_DAYS+10: continue
    ca=[float(r[1]) for r in rows]; ra=[float(r[2])/100.0 for r in rows]
    aa=[float(r[3]) if r[3] else 0 for r in rows]; dts=[str(r[0])[:10] for r in rows]
    for i in range(FEAT_WIN,len(rows)-FWD_DAYS):
        dt=dts[i]; v=vd.get((code,dt),{})
        feat=compute_features(ca[i-FEAT_WIN:i+1],aa[i-FEAT_WIN:i+1],ra[i-FEAT_WIN:i+1],v)
        gv=[gtja_val(code,dt,luks[gn]) for gn in GTJA_4]
        X_list.append(np.append(feat,np.array(gv,dtype=np.float32)))
        ret=(ca[i+FWD_DAYS]/ca[i]-1)*100
        y_list.append(ret); dl.append(dt)
    if (ci+1)%100==0:
        print(f"  {ci+1}/{len(codes)} stocks, {len(X_list)} samples [{time.time()-t0:.0f}s]",flush=True)
con.close()

X_raw=np.array(X_list,dtype=np.float32)
y=np.array(y_list,dtype=np.float32)
da=np.array(dl)
print(f"\nSamples: {len(X_raw):,}")
print(f"Label: mean={np.mean(y):+.2f}% std={np.std(y):.2f}%")

tm=da<SPLIT_DATE; vm=da>=SPLIT_DATE
X_tr_raw,y_tr=X_raw[tm],y[tm]
X_va_raw,y_va=X_raw[vm],y[vm]
print(f"Train: {len(X_tr_raw):,} ({tm.mean()*100:.0f}%)")
print(f"Val:   {len(X_va_raw):,} ({vm.mean()*100:.0f}%)")

# Standardize from train only
ns={}
for j in range(23):
    v=X_tr_raw[:,j]; ok=v[~np.isnan(v)]
    if len(ok)>0:
        ns[f'feat_{j}']={'mean':float(np.mean(ok)),'std':float(np.std(ok)),'low':float(np.percentile(ok,1)),'high':float(np.percentile(ok,99))}

def norm(X,s):
    Xn=X.copy()
    for j in range(23):
        k=f'feat_{j}'
        if k in s and s[k]['std']>0:
            Xn[:,j]=np.clip(Xn[:,j],s[k]['low'],s[k]['high'])
            Xn[:,j]=(Xn[:,j]-s[k]['mean'])/s[k]['std']
    return np.nan_to_num(Xn,nan=0.0)

X_tr=norm(X_tr_raw,ns); X_va=norm(X_va_raw,ns)

# Save norm stats
with open(OUT_DIR/'v6_norm_stats_40d_variants.json','w') as f: json.dump(ns,f)

# ── 三种变种 ──
experiments = [
    ('A_Huber', {'objective':'huber','huber_delta':1.0,'metric':'l2','num_leaves':63,'learning_rate':0.03,
        'feature_fraction':0.8,'bagging_fraction':0.8,'bagging_freq':5,'min_data_in_leaf':100,
        'verbose':1,'num_threads':6,'max_depth':8,'device':'gpu','first_metric_only':True}),
    ('B_clipped15', {'objective':'regression','metric':'l2','num_leaves':63,'learning_rate':0.03,
        'feature_fraction':0.8,'bagging_fraction':0.8,'bagging_freq':5,'min_data_in_leaf':100,
        'verbose':1,'num_threads':6,'max_depth':8,'device':'gpu','first_metric_only':True}),
    ('C_MAE', {'objective':'mae','metric':'mae','num_leaves':63,'learning_rate':0.03,
        'feature_fraction':0.8,'bagging_fraction':0.8,'bagging_freq':5,'min_data_in_leaf':100,
        'verbose':1,'num_threads':6,'max_depth':8,'device':'gpu','first_metric_only':True}),
]

for exp_name, params in experiments:
    print(f"\n{'='*60}")
    print(f"Training {exp_name}")
    print(f"{'='*60}")
    t1=time.time()
    
    y_tr_use = y_tr.copy()
    y_va_use = y_va.copy()
    y_tr_cont = y_tr  # for IC computation
    y_va_cont = y_va
    
    if exp_name == 'B_clipped15':
        y_tr_use = np.clip(y_tr_use, -15, 15)
        y_va_use = np.clip(y_va_use, -15, 15)
    
    dt=lgb.Dataset(X_tr, y_tr_use)
    dv=lgb.Dataset(X_va, y_va_use, reference=dt)
    
    model=lgb.train(params, dt, num_boost_round=1000,
                    valid_sets=[dt,dv], valid_names=['train','val'],
                    callbacks=[lgb.early_stopping(30), lgb.log_evaluation(50)])
    
    bi=model.best_iteration
    pv=model.predict(X_va, num_iteration=bi)
    icv=stats.spearmanr(pv, y_va_cont)[0]
    pt=model.predict(X_tr, num_iteration=bi)
    ict=stats.spearmanr(pt, y_tr_cont)[0]
    
    # Decile on val
    va=np.array(list(zip(pv,y_va_cont)))
    va=va[va[:,0].argsort()]
    d10=len(va)//10
    spreads=[]
    for d in range(10):
        s,e=d*d10,(d+1)*d10 if d<9 else len(va)
        spreads.append(np.mean(va[s:e,1]))
    sp=spreads[-1]-spreads[0]
    hr=np.mean(va[-d10:,1]>0)*100
    
    print(f"\n  {exp_name}:")
    print(f"  Best trees: {bi}")
    print(f"  Train IC: {ict:.4f}")
    print(f"  Val IC:   {icv:.4f}")
    print(f"  Spread:   {sp:.1f}%")
    print(f"  D10 hit:  {hr:.0f}%")
    for d in range(10):
        print(f"    D{d+1}: {spreads[d]:+.2f}%")
    
    # Save model
    out_name = f'lgb_reg_40d_{exp_name.lower()}.txt'
    model.save_model(str(OUT_DIR/out_name), num_iteration=bi)
    print(f"  Saved: {out_name} ({bi} trees, val IC={icv:.4f})")
    print(f"  Time: {time.time()-t1:.0f}s")

print(f"\n{'='*60}")
print(f"Total time: {time.time()-t0:.0f}s")
