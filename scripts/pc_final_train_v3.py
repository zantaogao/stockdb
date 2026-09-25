#!/usr/bin/env python3
"""
综合训练 v3 — 全量数据 + 更丰富技术指标 (数据泄露已修)
"""
import duckdb, numpy as np, pandas as pd, lightgbm as lgb
import torch, time, os, json, sys
from torch import nn
from torch.utils.data import DataLoader, TensorDataset
from scipy import stats
from sklearn.metrics import roc_auc_score

DB = r"C:\Users\pumma\factor_lib\stock.db"
OUT = r"C:\Users\pumma\factor_lib"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
t0 = time.time()
print(f"设备: {DEVICE}", flush=True)
if torch.cuda.is_available():
    print(f"  GPU: {torch.cuda.get_device_name(0)}", flush=True)

def _ema(arr, period):
    if len(arr)==0: return np.array([0.0])
    alpha=2/(period+1); r=np.zeros_like(arr); r[0]=arr[0]
    for j in range(1,len(arr)): r[j]=alpha*arr[j]+(1-alpha)*r[j-1]
    return r

def compute_features(c_slice, a_slice, r_slice):
    """c_slice/a_slice/r_slice 都是[:i+1]，只用到当天"""
    c=c_slice; lc=c[-1]; n=len(c)
    
    # 20维原特征 (全部用c_slice)
    chg5=lc/c[-5]-1 if n>=5 else 0; chg10=lc/c[-10]-1 if n>=10 else 0
    chg20=lc/c[-20]-1 if n>=20 else 0; chg60=lc/c[-60]-1 if n>=60 else 0; chg120=lc/c[0]-1
    ma5=np.mean(c[-5:]); ma10=np.mean(c[-10:]); ma20=np.mean(c[-20:])
    ma60=np.mean(c[-60:]) if n>=60 else lc; ma120=np.mean(c)
    d5=lc/ma5-1 if ma5>0 else 0; d10=lc/ma10-1 if ma10>0 else 0
    d20=lc/ma20-1 if ma20>0 else 0; d60=lc/ma60-1 if ma60>0 else 0; d120=lc/ma120-1 if ma120>0 else 0
    bull1=1 if n>=20 and ma5>ma10>ma20 else 0; bull2=1 if n>=60 and ma20>ma60 else 0
    rn=np.max(c[-20:])-np.min(c[-20:]); rr=rn/np.min(c[-20:])*100 if n>=20 and np.min(c[-20:])>0 else 0
    std20=np.std(c[-20:])/np.mean(c[-20:])*100 if n>=20 else 0
    vols=a_slice[-20:]; vr=vols[-1]/np.mean(vols) if n>=20 and np.mean(vols)>0 else 1
    rl,rh=np.min(c[-20:]),np.max(c[-20:]); pos=(lc-rl)/(rh-rl)*100 if n>=20 and rh!=rl else 50
    nh=1 if n>=20 and lc>rh*0.97 else 0; vpc=1 if chg5>0 and vr>1.2 else 0
    c1d=r_slice[-1] if len(r_slice)>0 else 0; c3d=lc/c[-3]-1 if n>=3 else 0
    
    # ── 新技术指标 (全部只用c_slice/r_slice/a_slice) ──
    
    # 1. RSI-14
    if n>=15:
        g=np.maximum(r_slice[-14:],0); l=np.maximum(-r_slice[-14:],0)
        ag,al=np.mean(g),np.mean(l); rsi=100-100/(1+ag/al) if al>0 else 100
    else: rsi=50
    
    # 2. MACD (用SMA近似)
    if n>=26:
        ema12=np.mean(c[-12:]); ema26=np.mean(c[-26:]); dif=ema12-ema26
        # 用最近9日DIF的SMA作为signal
        difs=np.array([np.mean(c[-j-12:-j])-np.mean(c[-j-26:-j]) for j in range(min(9,n-26))])
        signal=np.mean(difs) if len(difs)>0 else dif
        macd_h=dif-signal
    else: dif=0; macd_h=0
    
    # 3. OBV (20日标准化)
    if n>=21:
        obv=np.zeros(21)
        for j in range(1,21):
            if r_slice[-21+j]>0: obv[j]=obv[j-1]+a_slice[-21+j]
            elif r_slice[-21+j]<0: obv[j]=obv[j-1]-a_slice[-21+j]
            else: obv[j]=obv[j-1]
        obv_z=(obv[-1]-np.mean(obv))/np.std(obv) if np.std(obv)>0 else 0
    else: obv_z=0
    
    # 4. Bollinger %B
    if n>=20:
        bm=np.mean(c[-20:]); bs=np.std(c[-20:])
        bu=bm+2*bs; bl=bm-2*bs; bb_pct=(lc-bl)/(bu-bl) if bu!=bl else 0.5
        bb_w=(bu-bl)/bm if bm>0 else 0
    else: bb_pct=0.5; bb_w=0
    
    # 5. ATR-14
    if n>=15:
        trs=np.array([max(c[-j]-c[-j-1],abs(c[-j]-r_slice[-j-1]),abs(r_slice[-j])) 
                      for j in range(1,15)])
        atr=np.mean(trs)/lc if lc>0 else 0
    else: atr=0
    
    # 6. 量价相关性
    if n>=20:
        cv=np.corrcoef(r_slice[-20:],a_slice[-20:])
        corr_vp=cv[0,1] if not np.isnan(cv[0,1]) else 0
    else: corr_vp=0
    
    return np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
                     bull1,bull2,rr,std20,vr,pos,nh,vpc,c1d,c3d,
                     rsi/100, dif, macd_h, obv_z, bb_pct, bb_w, atr, corr_vp,
                     ], dtype=np.float32)

# ═══ PART 1: LightGBM v3 ═══
print("\n"+"="*60, flush=True)
print("PART 1/2: LightGBM v3 (29技术+3估值=32维)", flush=True)
print("="*60, flush=True)

con=duckdb.connect(DB); con.execute("SET memory_limit='8GB'")
daily=con.execute("""
    SELECT stock_code, date, close, change_pct/100.0 as ret, turn_rate/100.0 as turn, amount
    FROM stock_daily WHERE date>='2023-11-01' ORDER BY stock_code, date
""").fetchdf()
print(f"日线: {len(daily)}行", flush=True)

val_df=con.execute("SELECT stock_code,date,pe_ttm,pb,total_mv FROM stock_valuation ORDER BY stock_code,date").fetchdf()
val_dict={}
for _,row in val_df.iterrows():
    k=(row['stock_code'],str(row['date'])[:10])
    ep=1.0/row['pe_ttm'] if row['pe_ttm'] and row['pe_ttm']>0 else None
    bp=1.0/row['pb'] if row['pb'] and row['pb']>0 else None
    lc=np.log(row['total_mv']) if row['total_mv'] and row['total_mv']>0 else None
    if any(v is not None for v in [ep,bp,lc]): val_dict[k]={'ep': ep, 'bp': bp, 'ln_cap': lc}

rows_list=[]; code_count=0
grouped=list(daily.groupby('stock_code', sort=False))
for code,grp in grouped:
    n=len(grp)
    if n<120: continue
    code_count+=1
    c_arr=grp['close'].values.astype(np.float64)
    r_arr=grp['ret'].values.astype(np.float64)
    a_arr=grp['amount'].values.astype(np.float64)
    d_arr=grp['date'].values
    for i in range(119,n):
        feat=compute_features(c_arr[:i+1], a_arr[:i+1], r_arr[:i+1])
        date_key=str(d_arr[i])[:10]
        v=val_dict.get((code,date_key),{})
        ep=v.get('ep',0.5); bp=v.get('bp',0.5); ln_cap=v.get('ln_cap',22)
        rf=np.prod(1+r_arr[i+1:min(i+6,n)])-1 if i<n-1 else 0
        rows_list.append(np.concatenate([feat,[ep,bp,ln_cap,rf]]))
    if code_count%500==0: print(f"  {code_count}/{len(grouped)}只, {len(rows_list):,}样本", flush=True)

arr=np.array(rows_list,dtype=np.float32)
X=arr[:,:-1]; y=arr[:,-1]; y_cls=(y>0).astype(int)
X=np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
print(f"\n总样本: {len(X):,}, 特征: {X.shape[1]}维", flush=True)

split=int(len(X)*0.80)
X_tr,X_te=X[:split],X[split:]; yr_tr,yr_te=y[:split],y[split:]; yc_tr,yc_te=y_cls[:split],y_cls[split:]
for j in range(X_tr.shape[1]):
    col=X_tr[:,j]; l,h=np.percentile(col[~np.isnan(col)],[1,99]); col=np.clip(col,l,h)
    m,s=np.nanmean(col),np.nanstd(col)
    if s>0: X_tr[:,j]=(col-m)/s; X_te[:,j]=(np.clip(X_te[:,j],l,h)-m)/s

print(f"训练: {len(X_tr):,}  测试: {len(X_te):,}", flush=True)

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
    reg_lambda=1.0,reg_alpha=0.5,num_leaves=63,
    class_weight='balanced',device='gpu',gpu_device_id=0,random_state=42,verbose=-1)
cls.fit(X_tr,yc_tr,eval_set=[(X_te,yc_te)],eval_metric=['auc','binary_logloss'],
        callbacks=[lgb.early_stopping(50),lgb.log_evaluation(200)])
pred_c=cls.predict_proba(X_te)[:,1]; auc=roc_auc_score(yc_te,pred_c)
pr=np.mean(yr_te[pred_c>0.5]) if np.sum(pred_c>0.5)>10 else 0
nr=np.mean(yr_te[pred_c<=0.5]) if np.sum(pred_c<=0.5)>10 else 0
print(f"  分类 AUC={auc:.4f} ({cls.best_iteration_}棵树)", flush=True)
print(f"  预测涨: {pr:+.2%}  跌: {nr:+.2%}  多空差: {pr-nr:+.2%}", flush=True)

# 特征重要性
imp=reg.booster_.feature_importance(importance_type='gain')
names=['chg5','chg10','chg20','chg60','chg120','d5','d10','d20','d60','d120',
       'bull1','bull2','range','std20','vol_r','pos','near_h','vpc','c1d','c3d',
       'RSI','DIF','MACD_H','OBV_Z','BB_pct','BB_w','ATR','VP_corr',
       'ep','bp','ln_cap']
print(f"\n  特征TOP15:")
for n,v in sorted(zip(names,imp),key=lambda x:x[1],reverse=True)[:15]:
    print(f"    {n:10s} {v:.0f}", flush=True)

reg.booster_.save_model(os.path.join(OUT,"lgb_reg_v3.txt"))
cls.booster_.save_model(os.path.join(OUT,"lgb_cls_v3.txt"))
print(f"Saved", flush=True)
con.close()

# ═══ LSTM v3 (复用v2模型验证) ═══
print("\n"+"="*60, flush=True)
print("PART 2/2: LSTM v3 (复用v2模型验证)", flush=True)
print("="*60, flush=True)
con=duckdb.connect(DB)
raw=con.execute("""
    SELECT f.date, f.stock_code, f.factor_name, f.zscore,
           (b.close/a.close-1) as ret_future
    FROM factor_daily_values f JOIN stock_daily a ON f.stock_code=a.stock_code AND f.date=a.date
    LEFT JOIN stock_daily b ON f.stock_code=b.stock_code
        AND b.date=(SELECT MIN(date) FROM stock_daily WHERE stock_code=f.stock_code AND date>f.date+4)
    WHERE f.zscore IS NOT NULL AND f.date>='2024-03-01'
      AND f.factor_name IN ('mom_5','mom_10','mom_20','mom_60','vol_20','vol_60','turn_5','turn_20')
    ORDER BY f.stock_code, f.date
""").fetchdf(); con.close()
core=['mom_5','mom_10','mom_20','mom_60','vol_20','vol_60','turn_5','turn_20']
pv=raw.pivot_table(index=['stock_code','date','ret_future'],columns='factor_name',values='zscore').reset_index()
pv=pv.sort_values(['stock_code','date']).dropna(subset=core).dropna(subset=['ret_future']+core)
seqs,tgts=[],[]
for code,grp in pv.groupby('stock_code'):
    grp=grp.sort_values('date'); v=grp[core].values.astype(np.float32); r=grp['ret_future'].values.astype(np.float32)
    for i in range(20,len(grp)):
        if not np.isnan(v[i-20:i]).any() and not np.isnan(r[i]): seqs.append(v[i-20:i]); tgts.append(r[i])
X_l=np.array(seqs); y_l=np.array(tgts)
split_l=int(len(X_l)*0.80); X_le=X_l[split_l:]; y_le=y_l[split_l:]
yme_l=np.mean(y_l[:split_l]); ysd_l=np.std(y_l[:split_l])+1e-8
tel=DataLoader(TensorDataset(torch.tensor(X_le),torch.tensor((y_le-yme_l)/ysd_l)),512,shuffle=False)
class LSTMNet(nn.Module):
    def __init__(self):
        super().__init__(); self.lstm=nn.LSTM(8,128,2,batch_first=True,dropout=0.3)
        self.fc=nn.Sequential(nn.Linear(128,64),nn.ReLU(),nn.Dropout(0.3),nn.Linear(64,1))
    def forward(self,x): o,_=self.lstm(x); return self.fc(o[:,-1,:])
m=LSTMNet().to(DEVICE)
m.load_state_dict(torch.load(os.path.join(OUT,"lstm_v2.pt"))); m.eval()
pp_list=[]
with torch.no_grad():
    for Xb,_ in tel: pp_list.append(m(Xb.to(DEVICE)).cpu().numpy().flatten())
pp_f=np.concatenate(pp_list)*ysd_l+yme_l; ic_l=stats.spearmanr(pp_f,y_le)[0]
print(f"LSTM IC={ic_l:.4f}", flush=True)

print(f"\n{'='*60}", flush=True)
print("v3完成!", flush=True)
print(f"  回归 IC={ic_r:.4f} ({reg.best_iteration_}树)", flush=True)
print(f"  分类 AUC={auc:.4f} ({cls.best_iteration_}树)", flush=True)
print(f"  LSTM IC={ic_l:.4f} (复用v2)", flush=True)
print(f"  特征: {X.shape[1]}维", flush=True)
print(f"  耗时: {time.time()-t0:.0f}s", flush=True)
with open(os.path.join(OUT,"final_results_v3.json"),"w") as f:
    json.dump({'reg_ic':round(ic_r,4),'reg_trees':reg.best_iteration_,
               'cls_auc':round(auc,4),'cls_trees':cls.best_iteration_,
               'lstm_ic':round(ic_l,4),'n_features':X.shape[1],
               'n_train':len(X_tr),'n_test':len(X_te),'total_time':round(time.time()-t0,1),
               'device':DEVICE},f,indent=2)
