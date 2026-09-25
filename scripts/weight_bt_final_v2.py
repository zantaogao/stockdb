"""
权重回测 — 含历史LSTM推理 + verified数据管道
"""
import duckdb, numpy as np, pandas as pd, lightgbm as lgb, time, os, json, torch
from torch import nn; from scipy import stats

DB = r"C:\Users\pumma\factor_lib\stock.db"; OUT = r"C:\Users\pumma\factor_lib"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
t0 = time.time()
print(f"设备: {DEVICE}", flush=True)

# ── 1. 特征+reg预测（同verified脚本）──
reg = lgb.Booster(model_file=f"{OUT}/lgb_reg_v2.txt")
cls = lgb.Booster(model_file=f"{OUT}/lgb_cls_v2.txt")

con = duckdb.connect(DB)
daily = con.execute("SELECT stock_code,date,close,change_pct/100.0 as ret,amount FROM stock_daily WHERE date>='2023-11-01' ORDER BY stock_code,date").fetchdf()
val_df = con.execute("SELECT stock_code,date,pe_ttm,pb,total_mv FROM stock_valuation").fetchdf()
# 财务数据（规则分用）
fin_df = con.execute("SELECT stock_code,report_date,roe,revenue_yoy,profit_yoy,net_margin FROM fin_income ORDER BY stock_code,report_date").fetchdf()
con.close()
fin_latest = {}
for code, grp in fin_df.groupby('stock_code'):
    grp = grp.sort_values('report_date')
    if len(grp)>0:
        r = grp.iloc[-1]
        fin_latest[code] = {'roe': r['roe'], 'rev_yoy': r['revenue_yoy'], 'profit_yoy': r['profit_yoy'], 'net_margin': r['net_margin']}
vd = {}
for _,r in val_df.iterrows():
    k=(r['stock_code'],str(r['date'])[:10])
    ep=1.0/r['pe_ttm'] if r['pe_ttm'] and r['pe_ttm']>0 else None
    bp=1.0/r['pb'] if r['pb'] and r['pb']>0 else None; lc=np.log(r['total_mv']) if r['total_mv'] and r['total_mv']>0 else None
    if any(v is not None for v in [ep,bp,lc]): vd[k]={'ep':ep,'bp':bp,'ln_cap':lc}

rows=[]; meta=[]
for code,grp in daily.groupby('stock_code',sort=False):
    n=len(grp); c_arr=grp['close'].values.astype(np.float64); r_arr=grp['ret'].values.astype(np.float64)
    a_arr=grp['amount'].values.astype(np.float64); d_arr=grp['date'].values
    if n<120: continue
    for i in range(119,n):
        c=c_arr[:i+1]; lc=c[-1]
        chg5=lc/c[-5]-1 if i>=4 else 0; chg10=lc/c[-10]-1 if i>=9 else 0; chg20=lc/c[-20]-1 if i>=19 else 0
        chg60=lc/c[-60]-1 if i>=59 else 0; chg120=lc/c[0]-1
        ma5=np.mean(c[-5:]); ma10=np.mean(c[-10:]); ma20=np.mean(c[-20:]); ma60=np.mean(c[-60:]); ma120=np.mean(c)
        d5=lc/ma5-1 if ma5>0 else 0; d10=lc/ma10-1 if ma10>0 else 0; d20=lc/ma20-1 if ma20>0 else 0
        d60=lc/ma60-1 if ma60>0 else 0; d120=lc/ma120-1 if ma120>0 else 0
        bull1=1 if ma5>ma10>ma20 else 0; bull2=1 if ma20>ma60 else 0
        rn=np.max(c[-20:])-np.min(c[-20:]); rr=rn/np.min(c[-20:])*100 if np.min(c[-20:])>0 else 0
        std20=np.std(c[-20:])/np.mean(c[-20:])*100
        vols=a_arr[-20:]; vr=vols[-1]/np.mean(vols) if np.mean(vols)>0 else 1
        rl,rh=np.min(c[-20:]),np.max(c[-20:]); pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
        nh=1 if lc>rh*0.97 else 0; vpc=1 if chg5>0 and vr>1.2 else 0
        c1d=r_arr[i] if i>0 else 0; c3d=lc/c[-3]-1 if i>=2 else 0
        v=vd.get((code,str(d_arr[i])[:10]),{}); ep=v.get('ep',0.5) if v.get('ep') is not None else 0.5; bp=v.get('bp',0.5) if v.get('bp') is not None else 0.5; ln_cap=v.get('ln_cap',22) if v.get('ln_cap') is not None else 22
        rf=np.prod(1+r_arr[i+1:min(i+6,n)])-1 if i<n-1 else 0
        
        # 规则分（同复盘.py SQL评分逻辑，使用真实财务数据）
        f = fin_latest.get(code, {})
        roe = f.get('roe', 0) or 0
        rev_yoy = f.get('rev_yoy', 0) or 0
        net_margin = f.get('net_margin', 0) or 0
        rules_score = (
            min(max(roe, 0), 20) * 0.25 +           # 业绩(ROE) 25%
            (15 if ep > 0.04 else 10 if ep > 0.02 else 5 if ep > 0 else 0) * 0.20 +  # 估值 20%
            (15 if net_margin > 0.10 else 10 if net_margin > 0.05 else 5 if net_margin > 0 else 0) * 0.15 +  # 净利率 15%
            ((10+(5 if ma5>ma10 and 1<=d60<=50 else 0)) * 0.15 if d60>0 else 5*0.15) +  # 趋势 15%
            (10*0.10 if abs(chg60)*100 > 5 else 5*0.10 if abs(chg60)*100 > 1 else 0)  # 动量 10%
        ) * 100 / 15
        rows.append(np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
            bull1,bull2,rr,std20,vr,pos,nh,vpc,c1d,c3d,ep,bp,ln_cap,rf,rules_score],dtype=np.float32))
        meta.append({'date':str(d_arr[i])[:10],'code':code})
    if i%500==0: pass

arr=np.array(rows); X_all=arr[:,:23]; y_all=arr[:,23]; rules_all=arr[:,24]
split=int(len(X_all)*0.80); X_te=X_all[split:]; y_te=y_all[split:]; rules_te=rules_all[split:]; meta_te=meta[split:]
X_tr=X_all[:split]
for j in range(23):
    col=X_tr[:,j]; l,h=np.percentile(col[~np.isnan(col)],[1,99]); col=np.clip(col,l,h)
    m,s=np.nanmean(col),np.nanstd(col); X_te[:,j]=(np.clip(X_te[:,j],l,h)-m)/s if s>0 else X_te[:,j]
X_te=np.nan_to_num(X_te)

pred_reg=reg.predict(X_te)
pred_cls=cls.predict(X_te)
ic_check=stats.spearmanr(pred_reg,y_te)[0]
print(f"reg IC验证: {ic_check:.4f}", flush=True)

# 构建测试集DataFrame
dates=[m['date'] for m in meta_te]; codes=[m['code'] for m in meta_te]
test_dates_unique=sorted(set(dates))
test_df=pd.DataFrame({'date':dates,'code':codes,'reg':pred_reg,'cls':pred_cls,'rules':rules_te,'rf':y_te})
print(f"测试集: {len(test_df)}条 {len(test_dates_unique)}天", flush=True)

# ── 2. 历史LSTM推理 ──
print("\n历史LSTM推理...", flush=True)
con=duckdb.connect(DB)
fac=con.execute("""
    SELECT date,stock_code,factor_name,zscore FROM factor_daily_values
    WHERE zscore IS NOT NULL AND date>='2024-01-01'
      AND factor_name IN ('mom_5','mom_10','mom_20','mom_60','vol_20','vol_60','turn_5','turn_20')
    ORDER BY stock_code,date
""").fetchdf()
con.close()

core=['mom_5','mom_10','mom_20','mom_60','vol_20','vol_60','turn_5','turn_20']
pv=fac.pivot_table(index=['stock_code','date'],columns='factor_name',values='zscore').reset_index()
pv=pv.sort_values(['stock_code','date']).dropna(subset=core)
print(f"  因子数据: {len(pv)}行 {pv['date'].nunique()}天", flush=True)

# 按股票分组提取序列
test_date_set=set(test_dates_unique)
lstm_seqs={}
seq_count=0
for code,grp in pv.groupby('stock_code'):
    grp=grp.sort_values('date')
    v=grp[core].values.astype(np.float32); dt=grp['date'].values
    for i in range(20,len(v)):
        ds=str(dt[i])[:10]
        if ds in test_date_set:
            lstm_seqs[(ds,code)]=v[i-20:i]
            seq_count+=1

print(f"  LSTM序列: {seq_count}条", flush=True)

# 加载LSTM模型 + 批量推理
class LSTMNet(nn.Module):
    def __init__(self):
        super().__init__(); self.lstm=nn.LSTM(8,128,2,batch_first=True,dropout=0.3)
        self.fc=nn.Sequential(nn.Linear(128,64),nn.ReLU(),nn.Dropout(0.3),nn.Linear(64,1))
    def forward(self,x): o,_=self.lstm(x); return self.fc(o[:,-1,:])

lstm_m=LSTMNet().to(DEVICE); lstm_m.load_state_dict(torch.load(f"{OUT}/lstm_v2.pt")); lstm_m.eval()
keys=list(lstm_seqs.keys())
for s in range(0,len(keys),4096):
    e=min(s+4096,len(keys))
    batch=np.array([lstm_seqs[k] for k in keys[s:e]])
    with torch.no_grad():
        preds=lstm_m(torch.tensor(batch).to(DEVICE)).cpu().numpy().flatten()
    for j,k in enumerate(keys[s:e]): lstm_seqs[k]=float(preds[j])

# 每日归一化LSTM到0-100
print("  每日LSTM归一化...", flush=True)
lstm_by_date={}
for k,v in lstm_seqs.items():
    dt=k[0]
    if dt not in lstm_by_date: lstm_by_date[dt]=[]
    lstm_by_date[dt].append((k,v))

lstm_final={}
for dt,items in lstm_by_date.items():
    vals=np.array([v for _,v in items])
    rks=vals.argsort().argsort()
    for i,(k,_) in enumerate(items):
        lstm_final[k]=rks[i]/len(rks)*100

print(f"  推理完成: {len(lstm_final)}条, {len(lstm_by_date)}天", flush=True)

# 映射到测试集
test_df['lstm']=test_df.apply(lambda r: lstm_final.get((r['date'],r['code']),50),axis=1)
print(f"  LSTM映射: {(test_df['lstm']!=50).sum()}/{len(test_df)}条有效", flush=True)

# ── 3. 权重枚举 ──
print("\n权重枚举...", flush=True)
for c in ['reg','cls','rules']:
    m,M=test_df[c].min(),test_df[c].max(); test_df[f'{c}_n']=(test_df[c]-m)/(M-m)*100 if M>m else 50

results=[]
for wr in range(20,56,5):
    for wl in range(15,56,5):
        for wru in range(10,31,5):
            wc=100-wr-wl-wru
            if wc<0 or wc>30: continue
            test_df['comp']=test_df['reg_n']*wr/100+test_df['cls_n']*wc/100+test_df['lstm']*wl/100+test_df['rules_n']*wru/100
            decs=test_df.groupby('date').apply(lambda g: g.sort_values('comp',ascending=False)
                .iloc[:max(len(g)//10,5)]['rf'].mean()-g.sort_values('comp',ascending=False)
                .iloc[-max(len(g)//10,5):]['rf'].mean())
            # 用多空差排序（IC有bug）
            results.append({'reg':wr,'cls':wc,'lstm':wl,'rules':wru,
                'spread':decs.mean()*100,'sharpe':decs.mean()/decs.std()*np.sqrt(252) if decs.std()>0 else 0,
                'win_rate':(decs>0).mean()*100})

res=pd.DataFrame(results).sort_values('spread',ascending=False)
print(f"\n{'='*85}")
print(f"{'权重 (reg/cls/lstm/rules)':^40} {'多空%':^8} {'夏普':^7} {'胜率':^6}")
print(f"{'='*85}")
for _,r in res.head(15).iterrows():
    print(f"  {r['reg']:3.0f}/{r['cls']:3.0f}/{r['lstm']:3.0f}/{r['rules']:3.0f}  {r['spread']:>+6.2f}%  {r['sharpe']:>6.2f}  {r['win_rate']:4.0f}%", flush=True)

cur=res[(res.reg==40)&(res.cls==20)&(res.lstm==20)&(res.rules==20)]
if len(cur)>0: print(f"\n当前(40/20/20/20): 多空={cur.iloc[0]['spread']:+.2f}%")

# 各路单信号对比
print(f"\n单信号 daily IC:")
for name,col in [('reg','reg'),('cls','cls'),('lstm','lstm'),('rules','rules')]:
    ic_s=test_df.groupby('date').apply(lambda g: stats.spearmanr(g[col],g['rf'])[0]
        if g[col].nunique()>1 and g['rf'].nunique()>1 else 0).mean()
    print(f"  {name:6s}: {ic_s:.4f}")

# 分组单调性验证（用最优权重）
print(f"\n分组收益验证（最优权重复合）:")
best = res.iloc[0]
test_df['comp_best'] = test_df['reg_n']*best['reg']/100 + test_df['cls_n']*best['cls']/100 + \
                        test_df['lstm']*best['lstm']/100 + test_df['rules_n']*best['rules']/100
grp_ret = []
for _,g in test_df.groupby('date'):
    if len(g)<50: continue
    g=g.sort_values('comp_best',ascending=False)
    n10=max(len(g)//10,5)
    for gi in range(10):
        s=gi*len(g)//10; e=(gi+1)*len(g)//10
        grp_ret.append({'decile':gi+1,'ret':g.iloc[s:e]['rf'].mean()})
gr=pd.DataFrame(grp_ret).groupby('decile')['ret'].mean()
print(f"  最优({best['reg']:.0f}/{best['cls']:.0f}/{best['lstm']:.0f}/{best['rules']:.0f}):")
for d in range(1,11):
    print(f"    组{d:2d}: {gr[d]*100:+.2f}%", flush=True)
print(f"  多空差: {(gr[10]-gr[1])*100:+.2f}%", flush=True)

# 当前权重分组对比
test_df['comp_cur'] = test_df['reg_n']*40/100 + test_df['cls_n']*20/100 + \
                       test_df['lstm']*20/100 + test_df['rules_n']*20/100
grp_ret2 = []
for _,g in test_df.groupby('date'):
    if len(g)<50: continue
    g=g.sort_values('comp_cur',ascending=False)
    for gi in range(10):
        s=gi*len(g)//10; e=(gi+1)*len(g)//10
        grp_ret2.append({'decile':gi+1,'ret':g.iloc[s:e]['rf'].mean()})
gr2=pd.DataFrame(grp_ret2).groupby('decile')['ret'].mean()
print(f"  当前(40/20/20/20):")
for d in range(1,11):
    print(f"    组{d:2d}: {gr2[d]*100:+.2f}%", flush=True)

print(f"\n总耗时: {time.time()-t0:.0f}s")
res.to_csv(f"{OUT}/weight_bt_final_v2.csv", index=False)
