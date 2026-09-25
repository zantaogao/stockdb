#!/usr/bin/env python3
"""生成49维norm_stats（不需重训20d）"""
import sys,json,time,math
import numpy as np
from pathlib import Path
from scipy.stats import skew,kurtosis
sys.path.insert(0,str(Path(__file__).parent.parent))
import duckdb
import lightgbm as lgb

BASE=Path.home()/'.hermes'/'stockdb';DB_PATH=BASE/'stock.db';MODEL_DIR=BASE/'models'
FWD_DAYS=20;SPLIT_TRAIN='2024-06-01'
MAX_LABEL=50.0

# 加载已训好的模型
t0=time.time()
model=lgb.Booster(model_file=str(MODEL_DIR/'lgb_reg_model_60d_83trees.bak'))
N_FEATS=model.num_feature()
print(f"模型: {model.num_trees()}棵, {N_FEATS}维")

conn=duckdb.connect(str(DB_PATH),read_only=True)

# 取股票（只取前2000只，够算统计量）
stocks=[r[0] for r in conn.execute("""SELECT stock_code FROM stock_info
    WHERE stock_code NOT LIKE '8%' AND stock_code NOT LIKE '4%'
    AND board!='北交所' AND (stock_name NOT LIKE '%ST%' OR stock_name IS NULL)
    ORDER BY stock_code LIMIT 2000""").fetchall()]
print(f"股票: {len(stocks)}")

# 加载行情、估值（同训练脚本）
vm=conn.execute("""SELECT stock_code,date,pe_ttm,pb,total_mv FROM stock_valuation ORDER BY stock_code,date""").fetchall()
val_map={}
for code,dt,pe,pb,mv in vm:
    e={}
    if pe and float(pe)>0:e['ep']=1./float(pe)
    if pb and float(pb)>0:e['bp']=1./float(pb)
    if mv and float(mv)>0:e['ln_cap']=np.log(float(mv))
    if e:val_map[(code,str(dt)[:10])]=e

ac=conn.execute("""SELECT stock_code,date,close,volume FROM stock_daily ORDER BY stock_code,date""").fetchall()
sd={}
for code,dt,close,vol in ac:sd.setdefault(code,[]).append((str(dt)[:10],float(close),float(vol or 0)))

# GTJA
gtja_c,gtja_n=None,[]
cp=MODEL_DIR/'gtja_compact.pkl'
if cp.exists():
    import pickle
    with open(cp,'rb') as f:gtja_c=pickle.load(f)
    gtja_n=sorted(gtja_c.keys())[:11]
    print(f"GTJA:{len(gtja_n)}")

# per-stock计算49维特征（同训练脚本）
Xa,Da=[],[]
for si,code in enumerate(stocks):
    r=sd.get(code,[]);r_d=[x[0] for x in r]
    c=np.array([x[1] for x in r]);v=np.array([x[2] for x in r])
    n_sd=len(c)
    if n_sd<81:continue
    p=np.zeros(n_sd);p[1:]=(c[1:]-c[:-1])/c[:-1]
    dm={d:i for i,d in enumerate(r_d)}
    gs={}
    if gtja_c:
        for gn in gtja_n:gs[gn]=gtja_c.get(gn,{}).get(code,{})

    # 用SQL算12基础特征（同训练脚本）
    rows=conn.execute(f"""SELECT
        (s.close/LAG(s.close,5)OVER w-1)chg5,(s.close/LAG(s.close,10)OVER w-1)chg10,
        (s.close/LAG(s.close,20)OVER w-1)chg20,(s.close/LAG(s.close,60)OVER w-1)chg60,
        (s.close/AVG(s.close)OVER(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)-1)d5,
        (s.close/AVG(s.close)OVER(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW)-1)d10,
        (s.close/AVG(s.close)OVER(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)-1)d20,
        (s.close/AVG(s.close)OVER(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)-1)d60,
        COALESCE(s.change_pct,0)/100 c1d,(s.close/LAG(s.close,3)OVER w-1)c3d,
        s.date
        FROM stock_daily s
        WHERE s.stock_code='{code}'
        WINDOW w AS(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)
        ORDER BY s.date DESC LIMIT 200
    """).fetchall()
    if not rows:continue

    for row in rows:
        chg5,chg10,chg20,chg60=row[0],row[1],row[2],row[3]
        d5,d10,d20,d60=row[4],row[5],row[6],row[7]
        c1d,c3d=row[8],row[9]
        dt=str(row[10])[:10];di=dm.get(dt)
        if di is None or di<20:continue
        b1=1 if d5>d10>d20 else 0;b2=1 if d20>d60 else 0
        f38=np.zeros(38)
        f38[0]=chg5;f38[1]=chg10;f38[2]=chg20;f38[3]=chg60;f38[4]=chg60
        f38[5]=d5;f38[6]=d10;f38[7]=d20;f38[8]=d60;f38[9]=d60
        f38[10]=b1;f38[11]=b2;f38[18]=c1d;f38[19]=c3d;f38[23:26]=0,0,0

        w=c[max(0,di-59):di+1];lc=w[-1]
        p20=p[max(0,di-19):di+1];w20=w[-20:];rl,rh=np.min(w20),np.max(w20)
        f38[12]=(rh-rl)/rl*100 if rl>0 else 0
        f38[13]=np.std(w20)/np.mean(w20)*100 if np.mean(w20)>0 else 0
        vw=v[max(0,di-19):di+1];f38[14]=vw[-1]/np.mean(vw) if np.mean(vw)>0 else 1
        f38[15]=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
        f38[16]=1 if lc>rh*.97 else 0;f38[17]=1 if chg5>0.01 and f38[14]>1.2 else 0
        ve=val_map.get((code,dt),{});f38[20]=ve.get('ep',.5);f38[21]=ve.get('bp',.5);f38[22]=ve.get('ln_cap',22.)
        f38[26]=float(skew(w20)) if len(w20)>=20 else 0
        f38[27]=float(kurtosis(w20,fisher=False)) if len(w20)>=20 else 3
        stk=0
        for s in reversed(np.sign(p20)):
            if s<0:stk+=1
            else:break
        f38[28]=stk;f38[29]=np.sum(np.sign(p20[-10:])>0)/10. if len(p20)>=10 else .5
        if di>=60:
            vo=float(np.std(p[max(0,di-59):di-19])*math.sqrt(252));vn=float(np.std(p20)*math.sqrt(252))
            f38[30]=vn/vo-1 if vo>0 else 0
        else:f38[30]=0
        ma20=np.mean(w20);ma60=np.mean(c[max(0,di-59):di+1]) if di>=59 else ma20
        f38[31]=chg5-(ma20/ma60-1) if ma60>0 else 0
        w60=c[max(0,di-59):di+1];f38[32]=float(kurtosis(w60,fisher=False)) if len(w60)>=60 else 3
        if len(w20)>=10:
            x5=np.arange(5);y5=w20[-5:]
            s5=float(np.sum((x5-x5.mean())*(y5-y5.mean()))/np.sum((x5-x5.mean())**2)) if np.sum((x5-x5.mean())**2)>0 else 0
            x10=np.arange(10);y10=w20[-10:]
            s10=float(np.sum((x10-x10.mean())*(y10-y10.mean()))/np.sum((x10-x10.mean())**2)) if np.sum((x10-x10.mean())**2)>0 else 0
            f38[33]=s5;f38[34]=s10;f38[35]=s5-s10
        else:f38[33]=f38[34]=f38[35]=0
        vw20=v[max(0,di-19):di+1];vr20=vw20[-1]/np.mean(vw20) if np.mean(vw20)>0 else 1
        f38[36]=1 if chg5<-.01 and vr20<.7 else 0;f38[37]=1 if(chg5>0 and vr20<.8)or(chg5<0 and vr20>1.2)else 0
        # GTJA
        gtja_v=[gs.get(gn,{}).get(dt,0.) for gn in gtja_n[:11]]
        feat=np.append(f38,gtja_v)
        Xa.append(feat);Da.append(dt)
    if(si+1)%200==0:print(f"  [{si+1}/{len(stocks)}] {sum(len(x) for x in Xa):,}样本 {time.time()-t0:.0f}s",flush=True)

X=np.array(Xa);Da=np.array(Da)
print(f"总样本:{len(X):,}")

# 只用训练集算stats
m_tr=Da<SPLIT_TRAIN;X_tr=X[m_tr]
print(f"训练集:{len(X_tr):,}")

ns={}
for j in range(N_FEATS):
    v=X_tr[:,j];v=v[~np.isnan(v)&~np.isinf(v)]
    if len(v)<100:continue
    lo,hi=float(np.percentile(v,.5)),float(np.percentile(v,99.5))
    ns[f'feat_{j}']={'mean':float(np.mean(v)),'std':float(np.std(v,ddof=1)),'low':lo,'high':hi}

# 恢复备份的模型到正式位置
import shutil
shutil.copy(str(MODEL_DIR/'lgb_reg_model_60d_83trees.bak'), str(MODEL_DIR/'lgb_reg_model.txt'))

with open(MODEL_DIR/'v6_norm_stats.json','w') as f:json.dump(ns,f,indent=2)
print(f"✅ v6_norm_stats.json 已保存 ({len(ns)}维)")
print(f"✅ lgb_reg_model.txt 已恢复 (83棵, IC=0.1224)")
print(f"⏱ {time.time()-t0:.0f}s")
