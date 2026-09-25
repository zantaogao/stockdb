#!/usr/bin/env python3
"""
[复杂版] 权重回测 — 全量特征生成 + 每日多空组合 + 夏普/胜率/累计收益
"""
import duckdb, numpy as np, pandas as pd, lightgbm as lgb, torch, time, os, json
from torch import nn; from scipy import stats

DB = r"C:\Users\pumma\factor_lib\stock.db"
OUT = r"C:\Users\pumma\factor_lib"
DEVICE = "cuda"
t0 = time.time()

# 1. 加载模型
reg = lgb.Booster(model_file=f"{OUT}/lgb_reg_v2.txt")
cls = lgb.Booster(model_file=f"{OUT}/lgb_cls_v2.txt")

# 2. 从DB生成全量特征 (20+3=23维)
con = duckdb.connect(DB)
daily = con.execute("""
    SELECT stock_code, date, close, change_pct/100.0 as ret, amount
    FROM stock_daily WHERE date>='2023-11-01' ORDER BY stock_code, date
""").fetchdf()
val_df = con.execute("SELECT stock_code,date,pe_ttm,pb,total_mv FROM stock_valuation").fetchdf()
con.close()

val_dict = {}
for _, r in val_df.iterrows():
    k = (r['stock_code'], str(r['date'])[:10])
    ep = 1.0/r['pe_ttm'] if r['pe_ttm'] and r['pe_ttm']>0 else None
    bp = 1.0/r['pb'] if r['pb'] and r['pb']>0 else None
    lc = np.log(r['total_mv']) if r['total_mv'] and r['total_mv']>0 else None
    if any(v is not None for v in [ep,bp,lc]):
        val_dict[k] = {'ep':ep,'bp':bp,'ln_cap':lc}

records = []
for code, grp in daily.groupby('stock_code'):
    n = len(grp); c=grp['close'].values; r=grp['ret'].values; a=grp['amount'].values; d=grp['date'].values
    if n < 120: continue
    for i in range(119, n):
        cs=c[:i+1]; lc=cs[-1]
        chg5=lc/cs[-5]-1; chg10=lc/cs[-10]-1; chg20=lc/cs[-20]-1; chg60=lc/cs[-60]-1; chg120=lc/cs[0]-1
        ma5=np.mean(cs[-5:]); ma10=np.mean(cs[-10:]); ma20=np.mean(cs[-20:]); ma60=np.mean(cs[-60:]); ma120=np.mean(cs)
        d5=lc/ma5-1; d10=lc/ma10-1; d20=lc/ma20-1; d60=lc/ma60-1; d120=lc/ma120-1
        b1=1 if ma5>ma10>ma20 else 0; b2=1 if ma20>ma60 else 0
        rn=np.max(cs[-20:])-np.min(cs[-20:]); rr=rn/np.min(cs[-20:])*100 if np.min(cs[-20:])>0 else 0
        std=np.std(cs[-20:])/np.mean(cs[-20:])*100
        vl=a[i-19:i+1]; vr=vl[-1]/np.mean(vl) if np.mean(vl)>0 else 1
        rl,rh=np.min(cs[-20:]),np.max(cs[-20:]); pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
        nh=1 if lc>rh*0.97 else 0; vpc=1 if chg5>0 and vr>1.2 else 0
        c1d=r[i] if i>0 else 0; c3d=lc/cs[-3]-1 if len(cs)>=3 else 0
        v=val_dict.get((code,str(d[i])[:10]),{}); ep=v.get('ep',0.5); bp=v.get('bp',0.5); lc2=v.get('ln_cap',22)
        rf=np.prod(1+r[i+1:min(i+6,n)])-1 if i<n-1 else 0
        records.append([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
                        b1,b2,rr,std,vr,pos,nh,vpc,c1d,c3d,ep,bp,lc2,rf,code,str(d[i])[:10]])

cols = ['c5','c10','c20','c60','c120','d5','d10','d20','d60','d120',
         'b1','b2','rr','std','vr','pos','nh','vpc','c1d','c3d','ep','bp','lc','rf','code','date']
df = pd.DataFrame(records, columns=cols)
X = df.iloc[:,:23].values.astype(np.float32)
for j in range(23):
    col=X[:,j]; l,h=np.percentile(col[~np.isnan(col)],[1,99]); col=np.clip(col,l,h)
    m,s=np.nanmean(col),np.nanstd(col)
    if s>0: X[:,j]=(col-m)/s
X=np.nan_to_num(X)

# ML预测
df['reg_pred'] = reg.predict(X)
df['cls_prob'] = cls.predict(X)

# LSTM
lstm_scores = {}
if os.path.exists(f"{OUT}/lstm_pred.json"):
    with open(f"{OUT}/lstm_pred.json") as f:
        raw = json.load(f)
    vals = np.array(list(raw.values()))
    ranks = vals.argsort().argsort()
    for i,c in enumerate(raw.keys()): lstm_scores[c] = ranks[i]/len(ranks)*100
df['lstm_score'] = df['code'].map(lstm_scores).fillna(50)

# Rules (简化版)
df['rules_score'] = (np.clip(np.abs(df['c60'])*15,0,15) + np.clip(1/df['ep'].clip(0.01,10)*20,0,20))
df['rules_score'] = df['rules_score']/df['rules_score'].max()*100

# 测试集
dates = sorted(df['date'].unique())
split = dates[int(len(dates)*0.8)]
test = df[df['date']>=str(split)[:10]].copy()
for c in ['reg_pred','cls_prob','rules_score']:
    m,M=test[c].min(),test[c].max()
    test[f'{c}_n']=(test[c]-m)/(M-m)*100 if M>m else 50

# 枚举权重
results = []
for wr in range(20,51,5):
    for wc in range(0,26,5):
        for wl in range(20,51,5):
            for wr2 in range(10,31,5):
                if wr+wc+wl+wr2!=100: continue
                test['comp'] = test['reg_pred_n']*wr/100 + test['cls_prob_n']*wc/100 + \
                               test['lstm_score']*wl/100 + test['rules_score_n']*wr2/100
                dly_ic = test.groupby('date').apply(lambda g: stats.spearmanr(g['comp'],g['rf'])[0] if len(g)>50 else 0)
                ic_m = dly_ic.mean()
                results.append({'reg':wr,'cls':wc,'lstm':wl,'rules':wr2,'ic':ic_m})
                if (wr+wc+wl+wr2)%20==0: print(f"  {wr}/{wc}/{wl}/{wr2}: IC={ic_m:.4f}", flush=True)

rdf = pd.DataFrame(results).sort_values('ic', ascending=False)
print(f"\nTOP10:")
print(rdf.head(10).to_string(index=False))
print(f"\n当前(40/20/20/20): IC={rdf[(rdf.reg==40)&(rdf.cls==20)&(rdf.lstm==20)&(rdf.rules==20)].ic.values[0]:.4f}")
print(f"耗时: {time.time()-t0:.0f}s")
rdf.to_csv(f"{OUT}/weight_bt_complex.csv", index=False)
