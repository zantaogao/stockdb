"""
LightGBM v4 — 70维特征 (31技术+估值 + 39GTJA因子)
全量数据 2024-01~2026-05

用法: python pc_final_train_v4.py
"""
import duckdb, numpy as np, pandas as pd, lightgbm as lgb, time, os, sys, pickle, gzip
from scipy import stats
from sklearn.metrics import roc_auc_score

DB = r"C:\Users\pumma\factor_lib\stock.db"
OUT = r"C:\Users\pumma\factor_lib"
t0 = time.time()

# 加载GTJA因子
pkl_path = os.path.join(OUT, "gtja_signals.pkl.gz")
print("加载GTJA因子...", flush=True)
with gzip.open(pkl_path, 'rb') as f:
    gtja_results = pickle.load(f)
gtja_names = list(gtja_results.keys())
print(f"  {len(gtja_names)}个GTJA因子", flush=True)

con = duckdb.connect(DB)
daily = con.execute("""
    SELECT stock_code, date, close, change_pct/100.0 as ret, amount
    FROM stock_daily WHERE date >= '2023-11-01' ORDER BY stock_code, date
""").fetchdf()
val_df = con.execute("SELECT stock_code,date,pe_ttm,pb,total_mv FROM stock_valuation").fetchdf()
con.close()
vd = {}
for _,r in val_df.iterrows():
    k=(r['stock_code'],str(r['date'])[:10])
    ep=1.0/r['pe_ttm'] if r['pe_ttm'] and r['pe_ttm']>0 else None
    bp=1.0/r['pb'] if r['pb'] and r['pb']>0 else None
    lc=np.log(r['total_mv']) if r['total_mv'] and r['total_mv']>0 else None
    if any(v is not None for v in [ep,bp,lc]): vd[k]={'ep':ep,'bp':bp,'ln_cap':lc}

# 特征生成
print("特征生成...", flush=True)
rows = []; cc = 0
for code, grp in daily.groupby('stock_code', sort=False):
    n=len(grp); c_arr=grp['close'].values.astype(np.float64)
    r_arr=grp['ret'].values.astype(np.float64); a_arr=grp['amount'].values.astype(np.float64)
    d_arr=grp['date'].values
    if n<120: continue; cc+=1
    for i in range(119,n):
        c=c_arr[:i+1]; lc=c[-1]
        chg5=lc/c[-5]-1; chg10=lc/c[-10]-1; chg20=lc/c[-20]-1
        chg60=lc/c[-60]-1; chg120=lc/c[0]-1
        ma5=np.mean(c[-5:]); ma10=np.mean(c[-10:]); ma20=np.mean(c[-20:]); ma60=np.mean(c[-60:]); ma120=np.mean(c)
        d5=lc/ma5-1; d10=lc/ma10-1; d20=lc/ma20-1; d60=lc/ma60-1; d120=lc/ma120-1
        b1=1 if ma5>ma10>ma20 else 0; b2=1 if ma20>ma60 else 0
        rn=np.max(c[-20:])-np.min(c[-20:]); rr=rn/np.min(c[-20:])*100 if np.min(c[-20:])>0 else 0
        std20=np.std(c[-20:])/np.mean(c[-20:])*100
        vols=a_arr[:i+1][-20:]; vr=vols[-1]/np.mean(vols) if np.mean(vols)>0 else 1
        rl,rh=np.min(c[-20:]),np.max(c[-20:]); pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
        nh=1 if lc>rh*0.97 else 0; vpc=1 if chg5>0 and vr>1.2 else 0
        c1d=r_arr[i] if i>0 else 0; c3d=lc/c[-3]-1 if len(c)>=3 else 0
        v=vd.get((code,str(d_arr[i])[:10]),{}); ep=v.get('ep',0.5); bp=v.get('bp',0.5); lc2=v.get('ln_cap',22)
        rf=np.prod(1+r_arr[i+1:min(i+6,n)])-1 if i<n-1 else 0
        
        # GTJA因子（查预计算结果）
        dt_str = str(d_arr[i])[:10]
        gtja_v = []
        for gn in gtja_names:
            sig = gtja_results[gn]
            if dt_str in sig.index and code in sig.columns:
                val = sig.loc[dt_str, code]
                gtja_v.append(float(val) if not np.isnan(val) else 0.0)
            else:
                gtja_v.append(0.0)
        
        rows.append(np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
            b1,b2,rr,std20,vr,pos,nh,vpc,c1d,c3d,ep,bp,lc2]+gtja_v+[rf], dtype=np.float32))
    
    if cc%500==0: print(f"  {cc}只 {len(rows):,}样本", flush=True)

arr=np.array(rows); X=arr[:,:-1]; y=arr[:,-1]; y_cls=(y>0).astype(int)
X=np.nan_to_num(X, nan=0.0)
print(f"\n总样本: {len(X):,} 特征: {X.shape[1]}维", flush=True)

split=int(len(X)*0.80); X_tr,X_te=X[:split],X[split:]; yr_tr,yr_te=y[:split],y[split:]; yc_tr,yc_te=y_cls[:split],y_cls[split:]
for j in range(X_tr.shape[1]):
    col=X_tr[:,j]; l,h=np.percentile(col[~np.isnan(col)],[1,99]); col=np.clip(col,l,h)
    m,s=np.nanmean(col),np.nanstd(col)
    if s>0: X_tr[:,j]=(col-m)/s; X_te[:,j]=(np.clip(X_te[:,j],l,h)-m)/s
X_te=np.nan_to_num(X_te)

print(f"训练: {len(X_tr):,} 测试: {len(X_te):,}", flush=True)

# 回归
print("\n--- 回归 ---", flush=True)
reg=lgb.LGBMRegressor(n_estimators=3000,max_depth=6,learning_rate=0.003,
    subsample=0.8,colsample_bytree=0.8,min_child_samples=50,
    reg_lambda=1.0,reg_alpha=0.5,num_leaves=63,device='gpu',gpu_device_id=0,
    random_state=42,verbose=-1)
reg.fit(X_tr,yr_tr,eval_set=[(X_te,yr_te)],eval_metric=['rmse','mae'],
        callbacks=[lgb.early_stopping(50),lgb.log_evaluation(200)])
pred_r=reg.predict(X_te); ic_r=stats.spearmanr(pred_r,yr_te)[0]
print(f"\n  回归分组:")
si=np.argsort(pred_r)
for g in range(10):
    s=g*len(si)//10; e=(g+1)*len(si)//10; grp=si[s:e]
    print(f"    组{g+1:2d}: 预测{np.mean(pred_r[grp]):+.3%} -> 实际{np.mean(yr_te[grp]):+.3%}", flush=True)
print(f"  回归 IC={ic_r:.4f} ({reg.best_iteration_}棵树)", flush=True)

# 分类
print("\n--- 分类 ---", flush=True)
cls=lgb.LGBMClassifier(n_estimators=3000,max_depth=6,learning_rate=0.003,
    subsample=0.8,colsample_bytree=0.8,min_child_samples=50,
    reg_lambda=1.0,reg_alpha=0.5,num_leaves=63,class_weight='balanced',
    device='gpu',gpu_device_id=0,random_state=42,verbose=-1)
cls.fit(X_tr,yc_tr,eval_set=[(X_te,yc_te)],eval_metric=['auc','binary_logloss'],
        callbacks=[lgb.early_stopping(50),lgb.log_evaluation(200)])
pred_c=cls.predict_proba(X_te)[:,1]; auc=roc_auc_score(yc_te,pred_c)
pr=np.mean(yr_te[pred_c>0.5]) if np.sum(pred_c>0.5)>10 else 0
nr=np.mean(yr_te[pred_c<=0.5]) if np.sum(pred_c<=0.5)>10 else 0
print(f"  分类 AUC={auc:.4f} ({cls.best_iteration_}棵树)", flush=True)
print(f"  预测涨: {pr:+.2%} 跌: {nr:+.2%} 多空差: {pr-nr:+.2%}", flush=True)

# 特征重要性TOP20
imp=reg.booster_.feature_importance(importance_type='gain')
names=['c5','c10','c20','c60','c120','d5','d10','d20','d60','d120',
       'b1','b2','rr','std20','vr','pos','nh','vpc','c1d','c3d',
       'ep','bp','lc']+gtja_names
print(f"\n  特征TOP20:")
for n,v in sorted(zip(names,imp),key=lambda x:x[1],reverse=True)[:20]:
    short_n=n[:15]; print(f"    {short_n:15s} {v:.0f}", flush=True)

reg.booster_.save_model(os.path.join(OUT,"lgb_reg_v4.txt"))
cls.booster_.save_model(os.path.join(OUT,"lgb_cls_v4.txt"))
print(f"\nSaved v4 models", flush=True)

results={'reg_ic':round(ic_r,4),'reg_trees':reg.best_iteration_,
         'cls_auc':round(auc,4),'cls_trees':cls.best_iteration_,
         'n_features':X.shape[1],'n_train':len(X_tr),'n_test':len(X_te),
         'total_time':round(time.time()-t0,1)}
print(f"\n结果: {results}", flush=True)
with open(os.path.join(OUT,"final_results_v4.json"),"w") as f:
    json.dump(results,f,indent=2)
print(f"总耗时: {time.time()-t0:.0f}s", flush=True)
