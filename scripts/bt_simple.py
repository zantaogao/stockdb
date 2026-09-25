#!/usr/bin/env python3
"""
[简化版] 权重回测 — 只算IC，不模拟交易
直接用DB已有数据，不重新做全量特征
"""
import duckdb, numpy as np, pandas as pd, lightgbm as lgb, time, os, json
from scipy import stats

DB = r"C:\Users\pumma\factor_lib\stock.db"
OUT = r"C:\Users\pumma\factor_lib"
t0 = time.time()

# 1. 加载模型
reg = lgb.Booster(model_file=f"{OUT}/lgb_reg_v2.txt")
cls = lgb.Booster(model_file=f"{OUT}/lgb_cls_v2.txt")

# 2. 从DB取日线+估值，直接生成特征（复用v2训练的逻辑）
con = duckdb.connect(DB)
daily = con.execute("""
    SELECT stock_code, date, close, change_pct/100.0 as ret, amount
    FROM stock_daily WHERE date>='2023-11-01' ORDER BY stock_code, date
""").fetchdf()
val = con.execute("SELECT stock_code,date,pe_ttm,pb,total_mv FROM stock_valuation ORDER BY stock_code,date").fetchdf()
con.close()

# 估值字典
vd = {}
for _, r in val.iterrows():
    k=(r['stock_code'],str(r['date'])[:10])
    ep=1.0/r['pe_ttm'] if r['pe_ttm'] and r['pe_ttm']>0 else None
    bp=1.0/r['pb'] if r['pb'] and r['pb']>0 else None
    lc=np.log(r['total_mv']) if r['total_mv'] and r['total_mv']>0 else None
    if any(v is not None for v in [ep,bp,lc]): vd[k]={'ep':ep,'bp':bp,'ln_cap':lc}

# 逐股逐日算23维特征 + 标签
rows = []
for code, grp in daily.groupby('stock_code'):
    n=len(grp); c=grp['close'].values; r=grp['ret'].values; a=grp['amount'].values; d=grp['date'].values
    if n<120: continue
    for i in range(119, n):
        cs=c[:i+1]; lc=cs[-1]
        f23=[lc/cs[-5]-1, lc/cs[-10]-1, lc/cs[-20]-1, lc/cs[-60]-1, lc/cs[0]-1]
        ms=[np.mean(cs[-5:]),np.mean(cs[-10:]),np.mean(cs[-20:]),np.mean(cs[-60:]),np.mean(cs)]
        f23+=[lc/ms[0]-1, lc/ms[1]-1, lc/ms[2]-1, lc/ms[3]-1, lc/ms[4]-1]
        f23+=[1 if ms[0]>ms[1]>ms[2] else 0, 1 if ms[2]>ms[3] else 0]
        rn=np.max(cs[-20:])-np.min(cs[-20:]); f23+=[rn/np.min(cs[-20:])*100 if np.min(cs[-20:])>0 else 0]
        f23+=[np.std(cs[-20:])/np.mean(cs[-20:])*100]
        vl=a[i-19:i+1]; f23+=[vl[-1]/np.mean(vl) if np.mean(vl)>0 else 1]
        rl,rh=np.min(cs[-20:]),np.max(cs[-20:]); f23+=[(lc-rl)/(rh-rl)*100 if rh!=rl else 50]
        f23+=[1 if lc>rh*0.97 else 0, 1 if f23[0]>0 and f23[20]>1.2 else 0,
              r[i] if i>0 else 0, lc/cs[-3]-1 if len(cs)>=3 else 0]
        v=vd.get((code,str(d[i])[:10]),{}); f23+=[v.get('ep',0.5),v.get('bp',0.5),v.get('ln_cap',22)]
        rf=np.prod(1+r[i+1:min(i+6,n)])-1 if i<n-1 else 0
        rows.append(f23+[rf,code,str(d[i])[:10]])

cols=['c5','c10','c20','c60','c120','d5','d10','d20','d60','d120',
      'b1','b2','rr','std','vr','pos','nh','vpc','c1d','c3d','ep','bp','lc','rf','code','date']
df=pd.DataFrame(rows,columns=cols)
X=df.iloc[:,:23].values.astype(np.float32)
for j in range(23):
    col=X[:,j]; l,h=np.percentile(col[~np.isnan(col)],[1,99]); col=np.clip(col,l,h)
    m,s=np.nanmean(col),np.nanstd(col)
    if s>0: X[:,j]=(col-m)/s
X=np.nan_to_num(X)

df['reg_pred']=reg.predict(X)
df['cls_prob']=cls.predict(X)

# LSTM分数
ls={}
if os.path.exists(f"{OUT}/lstm_pred.json"):
    with open(f"{OUT}/lstm_pred.json") as f: raw=json.load(f)
    vals=np.array(list(raw.values())); rks=vals.argsort().argsort()
    for i,c in enumerate(raw.keys()): ls[c]=rks[i]/len(rks)*100
df['lstm_score']=df['code'].map(ls).fillna(50)

# Rules分：用SQL评分逻辑(简版)
df['rules_score']=( (np.clip(df['ep'].fillna(0.5)*50,0,25)) + # 估值
    np.clip(np.abs(df['d120'])*10,0,15) + # 年线偏离
    np.clip(np.abs(df['vr']-1)*20,0,10)   # 量比
).fillna(50)

# 测试集
dates=sorted(df['date'].unique())
split_dt=str(dates[int(len(dates)*0.8)])[:10]
test=df[df['date']>=split_dt].copy()
for c in ['reg_pred','cls_prob','rules_score']:
    m,M=test[c].min(),test[c].max()
    test[f'{c}_n']=(test[c]-m)/(M-m)*100 if M>m else 50

print(f"测试集: {len(test):,}条, {test['date'].nunique()}天", flush=True)

# 枚举所有权重组合
best = []
for wr in range(20,56,5):
    for wc in range(0,31,5):
        for wl in range(20,56,5):
            for wru in range(10,36,5):
                if wr+wc+wl+wru!=100 or (wc==0 and wl==0): continue
                test['comp']=test['reg_pred_n']*wr/100+test['cls_prob_n']*wc/100+\
                             test['lstm_score']*wl/100+test['rules_score_n']*wru/100
                ic=test.groupby('date').apply(lambda g: stats.spearmanr(g['comp'],g['rf'])[0] if len(g)>50 else 0).mean()
                best.append({'reg':wr,'cls':wc,'lstm':wl,'rules':wru,'ic':ic})

res=pd.DataFrame(best).sort_values('ic',ascending=False)
print(f"\n{'='*70}", flush=True)
print(f"{'权重组合 (reg/cls/lstm/rules)':^45} {'IC':>10}", flush=True)
print(f"{'='*70}", flush=True)
for _,r in res.head(15).iterrows():
    print(f"  {r['reg']:3d}/{r['cls']:3d}/{r['lstm']:3d}/{r['rules']:3d}  {'':25s} {r['ic']:.4f}", flush=True)

cur=res[(res.reg==40)&(res.cls==20)&(res.lstm==20)&(res.rules==20)]
if len(cur)>0: print(f"\n当前(40/20/20/20): IC={cur.iloc[0]['ic']:.4f}", flush=True)
print(f"\n耗时: {time.time()-t0:.0f}s", flush=True)
res.to_csv(f"{OUT}/weight_bt_simple.csv", index=False)
