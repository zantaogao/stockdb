"""
权重回测 — 基于verify_ic.py已验证的数据管道
"""
import duckdb, numpy as np, pandas as pd, lightgbm as lgb, time, os, json
from scipy import stats

DB = r"C:\Users\pumma\factor_lib\stock.db"; OUT = r"C:\Users\pumma\factor_lib"
t0 = time.time()

reg = lgb.Booster(model_file=f"{OUT}/lgb_reg_v2.txt")
print(f"模型: {reg.num_trees()}树 {reg.num_feature()}维", flush=True)

con = duckdb.connect(DB)
daily = con.execute("SELECT stock_code,date,close,change_pct/100.0 as ret,amount FROM stock_daily WHERE date>='2023-11-01' ORDER BY stock_code,date").fetchdf()
val_df = con.execute("SELECT stock_code,date,pe_ttm,pb,total_mv FROM stock_valuation").fetchdf()
con.close()

vd = {}
for _,r in val_df.iterrows():
    k=(r['stock_code'],str(r['date'])[:10])
    ep=1.0/r['pe_ttm'] if r['pe_ttm'] and r['pe_ttm']>0 else None
    bp=1.0/r['pb'] if r['pb'] and r['pb']>0 else None; lc=np.log(r['total_mv']) if r['total_mv'] and r['total_mv']>0 else None
    if any(v is not None for v in [ep,bp,lc]): vd[k]={'ep':ep,'bp':bp,'ln_cap':lc}

# ═══ 同verify_ic.py: numpy数组 ═══
rows=[]; meta=[]
for code,grp in daily.groupby('stock_code',sort=False):
    n=len(grp); c_arr=grp['close'].values.astype(np.float64)
    r_arr=grp['ret'].values.astype(np.float64); a_arr=grp['amount'].values.astype(np.float64)
    d_arr=grp['date'].values
    if n<120: continue
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
        rules_score = min(abs(chg60 if chg60 else 0)*20, 60) + min(abs(ep if ep else 0.5)*50, 20) + min(abs(d120 if d120 else 0)*10, 20)
        rows.append(np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
            bull1,bull2,rr,std20,vr,pos,nh,vpc,c1d,c3d,ep,bp,ln_cap,rf,rules_score],dtype=np.float32))
        meta.append({'date':str(d_arr[i])[:10],'code':code})
    if i%500==0: pass

arr=np.array(rows); X_all=arr[:,:23]; y_all=arr[:,23]; rules_all=arr[:,24]
split=int(len(X_all)*0.80); X_tr,X_te=X_all[:split],X_all[split:]; y_tr,y_te=y_all[:split],y_all[split:]
rules_tr,rules_te=rules_all[:split],rules_all[split:]
meta_te=meta[split:]

for j in range(23):
    col=X_tr[:,j]; l,h=np.percentile(col[~np.isnan(col)],[1,99]); col=np.clip(col,l,h)
    m,s=np.nanmean(col),np.nanstd(col); X_tr[:,j]=(col-m)/s if s>0 else col
    X_te[:,j]=(np.clip(X_te[:,j],l,h)-m)/s if s>0 else X_te[:,j]
X_te=np.nan_to_num(X_te)

# 预测
pred_reg=reg.predict(X_te)
ic_check=stats.spearmanr(pred_reg,y_te)[0]
print(f"\nreg IC验证: {ic_check:.4f} (期望0.135)", flush=True)

# 构建测试DataFrame
dates=[m['date'] for m in meta_te]; codes=[m['code'] for m in meta_te]
test_df=pd.DataFrame({'date':dates,'code':codes,'reg':pred_reg,'rules':rules_te,'rf':y_te})

# LSTM
lstm_path=f"{OUT}/lstm_pred.json"; lstm_scores={}
if os.path.exists(lstm_path):
    with open(lstm_path) as f: raw=json.load(f)
    vals=np.array(list(raw.values())); rks=vals.argsort().argsort()
    for i,c in enumerate(raw.keys()): lstm_scores[c]=rks[i]/len(rks)*100
test_df['lstm']=test_df['code'].map(lstm_scores).fillna(50)

# cls用默认0.5
test_df['cls']=0.5

# 归一化
for c in ['reg','rules']:
    m,M=test_df[c].min(),test_df[c].max(); test_df[f'{c}_n']=(test_df[c]-m)/(M-m)*100 if M>m else 50

# 权重枚举
results=[]
for wr in range(20,56,5):
    for wl in range(20,56,5):
        for wru in range(10,31,5):
            wc=100-wr-wl-wru
            if wc<0 or wc>30: continue
            test_df['comp']=test_df['reg_n']*wr/100+test_df['cls']*wc/100+test_df['lstm']*wl/100+test_df['rules_n']*wru/100
            ics=test_df.groupby('date').apply(lambda g: stats.spearmanr(g['comp'],g['rf'])[0]
                if g['comp'].nunique()>1 and g['rf'].nunique()>1 else 0)
            decs=test_df.groupby('date').apply(lambda g: g.sort_values('comp',ascending=False).iloc[:max(len(g)//10,5)]['rf'].mean()-g.sort_values('comp',ascending=False).iloc[-max(len(g)//10,5):]['rf'].mean())
            results.append({'reg':wr,'cls':wc,'lstm':wl,'rules':wru,'ic':ics.mean(),'spread':decs.mean()*100})

res=pd.DataFrame(results).sort_values('ic',ascending=False)
print(f"\n{'='*75}")
print(f"{'权重':^35} {'IC':^7} {'多空%':^8}")
print(f"{'='*75}")
for _,r in res.head(15).iterrows():
    print(f"  {r['reg']:3.0f}/{r['cls']:3.0f}/{r['lstm']:3.0f}/{r['rules']:3.0f}  {r['ic']:.4f}  {r['spread']:>+6.2f}%", flush=True)

cur=res[(res.reg==40)&(res.cls==20)&(res.lstm==20)&(res.rules==20)]
if len(cur)>0: print(f"\n当前(40/20/20/20): IC={cur.iloc[0]['ic']:.4f} 多空={cur.iloc[0]['spread']:+.2f}%")
print(f"\n耗时: {time.time()-t0:.0f}s")
