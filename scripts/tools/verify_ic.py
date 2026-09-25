"""验证：复现训练脚本的测试集IC"""
import duckdb, numpy as np, pandas as pd, lightgbm as lgb, os, time
from scipy import stats

DB = r"C:\Users\pumma\factor_lib\stock.db"; OUT = r"C:\Users\pumma\factor_lib"
t0 = time.time()

reg = lgb.Booster(model_file=f"{OUT}/lgb_reg_v2.txt")
print(f"模型: {reg.num_trees()}树 {reg.num_feature()}维", flush=True)

con = duckdb.connect(DB)
daily = con.execute("""
    SELECT stock_code, date, close, change_pct/100.0 as ret, turn_rate/100.0 as turn, amount
    FROM stock_daily WHERE date >= '2023-11-01' ORDER BY stock_code, date
""").fetchdf()
val_df = con.execute("SELECT stock_code,date,pe_ttm,pb,total_mv FROM stock_valuation").fetchdf()
con.close()

vd = {}
for _, r in val_df.iterrows():
    k=(r['stock_code'],str(r['date'])[:10])
    ep=1.0/r['pe_ttm'] if r['pe_ttm'] and r['pe_ttm']>0 else None
    bp=1.0/r['pb'] if r['pb'] and r['pb']>0 else None; lc=np.log(r['total_mv']) if r['total_mv'] and r['total_mv']>0 else None
    if any(v is not None for v in [ep,bp,lc]): vd[k]={'ep':ep,'bp':bp,'ln_cap':lc}

rows=[]; cc=0
for code, grp in daily.groupby('stock_code', sort=False):
    n=len(grp); c_arr=grp['close'].values.astype(np.float64); r_arr=grp['ret'].values.astype(np.float64); a_arr=grp['amount'].values.astype(np.float64); d_arr=grp['date'].values
    if n<120: continue; cc+=1
    for i in range(119,n):
        c=c_arr[:i+1]; lc=c[-1]
        chg5=lc/c[-5]-1 if i>=4 else 0; chg10=lc/c[-10]-1 if i>=9 else 0; chg20=lc/c[-20]-1 if i>=19 else 0
        chg60=lc/c[-60]-1 if i>=59 else 0; chg120=lc/c[0]-1
        ma5=np.mean(c[-5:]); ma10=np.mean(c[-10:]); ma20=np.mean(c[-20:]); ma60=np.mean(c[-60:]); ma120=np.mean(c)
        d5=lc/ma5-1 if ma5>0 else 0; d10=lc/ma10-1 if ma10>0 else 0; d20=lc/ma20-1 if ma20>0 else 0
        d60=lc/ma60-1 if ma60>0 else 0; d120=lc/ma120-1 if ma120>0 else 0
        bull1=1 if ma5>ma10>ma20 else 0; bull2=1 if ma20>ma60 else 0
        r20=np.max(c[-20:])-np.min(c[-20:]); rr=r20/np.min(c[-20:])*100 if np.min(c[-20:])>0 else 0
        std20=np.std(c[-20:])/np.mean(c[-20:])*100
        vols=a_arr[-20:]; vr=vols[-1]/np.mean(vols) if np.mean(vols)>0 else 1
        rl,rh=np.min(c[-20:]),np.max(c[-20:]); pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
        nh=1 if lc>rh*0.97 else 0; vpc=1 if chg5>0 and vr>1.2 else 0
        c1d=r_arr[i] if i>0 else 0; c3d=lc/c[-3]-1 if i>=2 else 0
        v=vd.get((code,str(d_arr[i])[:10]),{}); ep=v.get('ep',0.5); bp=v.get('bp',0.5); ln_cap=v.get('ln_cap',22)
        rf=np.prod(1+r_arr[i+1:min(i+6,n)])-1 if i<n-1 else 0
        rows.append(np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
            bull1,bull2,rr,std20,vr,pos,nh,vpc,c1d,c3d,ep,bp,ln_cap,rf], dtype=np.float32))
    if cc%500==0: print(f"  {cc}只 {len(rows):,}样本", flush=True)

arr=np.array(rows); X=arr[:,:23]; y=arr[:,23]
split=int(len(X)*0.80); X_tr,X_te=X[:split],X[split:]; y_tr,y_te=y[:split],y[split:]
for j in range(23):
    col=X_tr[:,j]; l,h=np.percentile(col[~np.isnan(col)],[1,99]); col=np.clip(col,l,h)
    m,s=np.nanmean(col),np.nanstd(col); X_tr[:,j]=(col-m)/s if s>0 else col
    X_te[:,j]=(np.clip(X_te[:,j],l,h)-m)/s if s>0 else X_te[:,j]
X_te=np.nan_to_num(X_te)

pred=reg.predict(X_te)
ic=stats.spearmanr(pred,y_te)[0]
# 分组
si=np.argsort(pred)
print(f"\n测试集: {len(y_te)}样本, IC={ic:.4f}", flush=True)
print(f"分组:")
for g in range(10):
    s=g*len(si)//10; e=(g+1)*len(si)//10; grp=si[s:e]
    print(f"  组{g+1:2d}: 预测{np.mean(pred[grp]):+.4f} 实际{np.mean(y_te[grp]):+.4f}", flush=True)
print(f"耗时: {time.time()-t0:.0f}s", flush=True)
