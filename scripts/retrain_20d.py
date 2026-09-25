#!/usr/bin/env python3
"""20d回归重训 v5 — 60天窗口, 49维(38基础+11GTJA), 特征顺序与features.py一致"""
import json,os,sys,time,math
import numpy as np
import lightgbm as lgb
from pathlib import Path
from scipy.stats import spearmanr,skew,kurtosis
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
sys.path.insert(0,str(Path(__file__).parent.parent))
import duckdb

BASE=Path.home()/'.hermes'/'stockdb'
MODEL_DIR=BASE/'models';DB_PATH=BASE/'stock.db'
SPLIT_TRAIN='2024-06-01';SPLIT_VAL='2025-01-01'
FWD_DAYS=20;MAX_LABEL=50.0;N_FEATS=49  # 38基础+11GTJA

def load_valmap(conn):
    vm=conn.execute("""SELECT stock_code,date,pe_ttm,pb,total_mv FROM stock_valuation ORDER BY stock_code,date""").fetchall()
    r={}
    for code,dt,pe,pb,mv in vm:
        e={}
        if pe and float(pe)>0:e['ep']=1./float(pe)
        if pb and float(pb)>0:e['bp']=1./float(pb)
        if mv and float(mv)>0:e['ln_cap']=np.log(float(mv))
        if e:r[(code,str(dt)[:10])]=e
    return r

def main():
    t0=time.time()
    print("="*65)
    print(f"20d回归重训 v5 — 60天窗口, {N_FEATS}维")
    print(f"  切分: {SPLIT_TRAIN}/{SPLIT_VAL}")
    print("="*65)

    conn=duckdb.connect(str(DB_PATH),read_only=True)
    stocks=[r[0] for r in conn.execute("""SELECT stock_code FROM stock_info
        WHERE stock_code NOT LIKE '8%' AND stock_code NOT LIKE '4%'
        AND board!='北交所' AND (stock_name NOT LIKE '%ST%' OR stock_name IS NULL)""").fetchall()]
    print(f"\n股票:{len(stocks)}")
    vm=load_valmap(conn);print(f"估值:{len(vm)}")

    # SQL窗口函数(60天)算12个基础特征
    print("\n🔨 SQL...")
    conn.execute(f"""
        CREATE TEMP TABLE feats AS
        SELECT s.stock_code,s.date,
            (s.close/LAG(s.close,5)OVER w-1)chg5,(s.close/LAG(s.close,10)OVER w-1)chg10,
            (s.close/LAG(s.close,20)OVER w-1)chg20,(s.close/LAG(s.close,60)OVER w-1)chg60,
            (s.close/AVG(s.close)OVER(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)-1)d5,
            (s.close/AVG(s.close)OVER(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW)-1)d10,
            (s.close/AVG(s.close)OVER(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)-1)d20,
            (s.close/AVG(s.close)OVER(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)-1)d60,
            (LEAD(s.close,{FWD_DAYS})OVER w/s.close-1)*100 "label",
            COALESCE(s.change_pct,0)/100 c1d,
            (s.close/LAG(s.close,3)OVER w-1)c3d
        FROM stock_daily s WINDOW w AS(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)
    """)
    conn.execute("""CREATE TEMP TABLE feats2 AS SELECT f.*,
        CASE WHEN d5>d10 AND d10>d20 THEN 1 ELSE 0 END bull1,
        CASE WHEN d20>d60 THEN 1 ELSE 0 END bull2 FROM feats f""")
    conn.execute("DELETE FROM feats2 WHERE chg60 IS NULL OR \"label\" IS NULL")
    conn.execute(f"DELETE FROM feats2 WHERE ABS(\"label\")>{MAX_LABEL}")
    n_v=conn.execute("SELECT COUNT(*)FROM feats2").fetchone()[0];print(f"  有效:{n_v:,}")

    # 导出—12列SQL特征
    arr=conn.execute("""SELECT stock_code,date,chg5,chg10,chg20,chg60,
        d5,d10,d20,d60,bull1,bull2,c1d,c3d,"label" FROM feats2 ORDER BY stock_code,date""").fetchall()
    codes=[r[0] for r in arr];dates=[str(r[1])[:10] for r in arr]
    raw=np.array([list(r[2:]) for r in arr],dtype=np.float64)
    y=raw[:,-1].copy();raw=raw[:,:-1]  # remove label
    print(f"  原始特征:{raw.shape} y:{y.shape}")

    # 重建38维F_base（与features.py顺序一致）
    n=len(codes)
    F=np.zeros((n,38),dtype=np.float64)
    # 0-4: chg5,chg10,chg20,chg60,chg120(=chg60)
    F[:,0]=raw[:,0];F[:,1]=raw[:,1];F[:,2]=raw[:,2];F[:,3]=raw[:,3];F[:,4]=raw[:,3]
    # 5-9: d5,d10,d20,d60,d120(=d60)
    F[:,5]=raw[:,4];F[:,6]=raw[:,5];F[:,7]=raw[:,6];F[:,8]=raw[:,7];F[:,9]=raw[:,7]
    # 10-11: bull1,bull2
    F[:,10]=raw[:,8];F[:,11]=raw[:,9]
    # 18-19: c1d,c3d
    F[:,18]=raw[:,10];F[:,19]=raw[:,11]
    # 23-25: ex5,ex10,ex20 = 0 (无指数数据)
    F[:,23]=F[:,24]=F[:,25]=0.0
    print(f"  38维F_base初始完成")

    # 补充分组
    unique_codes=list(dict.fromkeys(codes));code_to_idx={}
    for i,c in enumerate(codes):code_to_idx.setdefault(c,[]).append(i)

    # 加载行情
    print("📡 行情...")
    all_close=conn.execute("""SELECT stock_code,date,close,volume FROM stock_daily ORDER BY stock_code,date""").fetchall()
    sd={}
    for code,dt,close,vol in all_close:sd.setdefault(code,[]).append((str(dt)[:10],float(close),float(vol or 0)))
    conn.close()

    # GTJA
    gtja_c,gtja_n=None,[]
    cp=MODEL_DIR/'gtja_compact.pkl'
    if cp.exists():
        import pickle
        with open(cp,'rb') as f:gtja_c=pickle.load(f)
        gtja_n=sorted(gtja_c.keys())[:11]
        print(f"  GTJA:{len(gtja_n)}")

    gtja_cols=np.zeros((n,11),dtype=np.float64)
    # GTJA日期快速查找：date_str → 该字符串前一天/后一天的date_str
    # 预建一个date_prev_map:{d:前一个交易日的d}
    all_dt=sorted(set(dates))
    dt_prev={}
    for i,d in enumerate(all_dt):
        if i>0:dt_prev[d]=all_dt[i-1]

    print("\n🔨 per-stock特征+GTJA...")
    for si,code in enumerate(unique_codes):
        idxs=code_to_idx[code]
        r=sd.get(code,[])
        if not r:continue
        r_d=[x[0] for x in r];c=np.array([x[1] for x in r]);v=np.array([x[2] for x in r])
        nsd=len(c);p=np.zeros(nsd);p[1:]=(c[1:]-c[:-1])/c[:-1]
        dm={d:i for i,d in enumerate(r_d)}
        gs={}
        if gtja_c:
            for gn in gtja_n:gs[gn]=gtja_c.get(gn,{}).get(code,{})
        for j,idx in enumerate(idxs):
            dt=dates[idx];di=dm.get(dt)
            if di is None or di<20:continue
            w=c[max(0,di-59):di+1];lc=w[-1]
            p20=p[max(0,di-19):di+1];w20=w[-20:];rl,rh=np.min(w20),np.max(w20)
            # 12-17: rr,std20,vr,pos,nh,vpc
            F[idx,12]=(rh-rl)/rl*100 if rl>0 else 0
            F[idx,13]=np.std(w20)/np.mean(w20)*100 if np.mean(w20)>0 else 0
            vw=v[max(0,di-19):di+1];F[idx,14]=vw[-1]/np.mean(vw) if np.mean(vw)>0 else 1
            F[idx,15]=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
            F[idx,16]=1 if lc>rh*.97 else 0
            chg5=F[idx,0];F[idx,17]=1 if chg5>0.01 and F[idx,14]>1.2 else 0
            # 20-22: ep,bp,ln_cap
            ve=vm.get((code,dt),{});F[idx,20]=ve.get('ep',.5);F[idx,21]=ve.get('bp',.5);F[idx,22]=ve.get('ln_cap',22.)
            # 26-31: skew20,kurt20,dn_streak,up_ratio10,vol_chg,rel_str
            F[idx,26]=float(skew(w20)) if len(w20)>=20 else 0
            F[idx,27]=float(kurtosis(w20,fisher=False)) if len(w20)>=20 else 3
            stk=0
            for s in reversed(np.sign(p20)):
                if s<0:stk+=1
                else:break
            F[idx,28]=stk;F[idx,29]=np.sum(np.sign(p20[-10:])>0)/10. if len(p20)>=10 else .5
            if di>=60:
                vo=float(np.std(p[max(0,di-59):di-19])*math.sqrt(252))
                vn=float(np.std(p20)*math.sqrt(252))
                F[idx,30]=vn/vo-1 if vo>0 else 0
            else:F[idx,30]=0
            ma20=np.mean(w20);ma60=np.mean(c[max(0,di-59):di+1]) if di>=59 else ma20
            F[idx,31]=chg5-(ma20/ma60-1) if ma60>0 else 0
            # 32-37: kurt60,slope5,slope10,accel,vp_shrink,vp_div
            w60=c[max(0,di-59):di+1]
            F[idx,32]=float(kurtosis(w60,fisher=False)) if len(w60)>=60 else 3
            if len(w20)>=10:
                x5=np.arange(5);y5=w20[-5:]
                s5=float(np.sum((x5-x5.mean())*(y5-y5.mean()))/np.sum((x5-x5.mean())**2)) if np.sum((x5-x5.mean())**2)>0 else 0
                x10=np.arange(10);y10=w20[-10:]
                s10=float(np.sum((x10-x10.mean())*(y10-y10.mean()))/np.sum((x10-x10.mean())**2)) if np.sum((x10-x10.mean())**2)>0 else 0
                F[idx,33]=s5;F[idx,34]=s10;F[idx,35]=s5-s10
            else:F[idx,33]=F[idx,34]=F[idx,35]=0
            vw20=v[max(0,di-19):di+1];vr20=vw20[-1]/np.mean(vw20) if np.mean(vw20)>0 else 1
            F[idx,36]=1 if chg5<-.01 and vr20<.7 else 0;F[idx,37]=1 if(chg5>0 and vr20<.8)or(chg5<0 and vr20>1.2)else 0
            # GTJA
            for gi,gn in enumerate(gtja_n[:11]):
                val=gs.get(gn,{}).get(dt,0.)
                if val==0. and gs.get(gn):
                    pd=dt
                    for _ in range(15):
                        pd=dt_prev.get(pd)
                        if pd is None:break
                        if pd in gs[gn]:val=gs[gn][pd];break
                gtja_cols[idx,gi]=val
        if(si+1)%500==0:print(f"  [{si+1}/{len(unique_codes)}] {time.time()-t0:.0f}s",flush=True)

    X=np.column_stack([F,gtja_cols])[:,:N_FEATS]
    X=np.nan_to_num(X,nan=0.,posinf=0.,neginf=0.)
    print(f"  X:{X.shape}")

    # 切分
    Da=np.array(dates)
    m_tr=Da<SPLIT_TRAIN;m_va=(Da>=SPLIT_TRAIN)&(Da<SPLIT_VAL);m_te=Da>=SPLIT_VAL
    X_tr,y_tr=X[m_tr],y[m_tr];X_va,y_va=X[m_va],y[m_va];X_te,y_te=X[m_te],y[m_te]
    mk=np.abs(y_tr)<=MAX_LABEL;X_tr,y_tr=X_tr[mk],y_tr[mk]
    mk_va=np.abs(y_va)<=MAX_LABEL;X_va,y_va=X_va[mk_va],y_va[mk_va]
    mk_te=np.abs(y_te)<=MAX_LABEL;X_te,y_te=X_te[mk_te],y_te[mk_te]
    print(f"  训练:{len(X_tr):,} 验证:{len(X_va):,} 测试:{len(X_te):,}")

    # 标准化
    ns={}
    for j in range(N_FEATS):
        v=X_tr[:,j];v=v[~np.isnan(v)&~np.isinf(v)]
        if len(v)<100:continue
        lo,hi=float(np.percentile(v,.5)),float(np.percentile(v,99.5))
        ns[f'feat_{j}']={'mean':float(np.mean(v)),'std':float(np.std(v,ddof=1)),'low':lo,'high':hi}
    def norm(Xi):
        Xo=Xi.copy()
        for j in range(N_FEATS):
            k=f'feat_{j}'
            if k in ns and ns[k]['std']>0:
                s=ns[k];Xo[:,j]=np.clip(Xo[:,j],s['low'],s['high']);Xo[:,j]=(Xo[:,j]-s['mean'])/s['std']
        return Xo

    print("\n🏋️ 训练...")
    model=lgb.train({'objective':'regression','metric':'l2','learning_rate':0.02,
        'num_leaves':127,'max_depth':10,'feature_fraction':0.7,'bagging_fraction':0.8,
        'bagging_freq':5,'min_data_in_leaf':50,'num_threads':8,'verbosity':-1,'seed':42},
        lgb.Dataset(norm(X_tr),y_tr.astype(np.float32)),num_boost_round=5000,
        valid_sets=[lgb.Dataset(norm(X_va),y_va.astype(np.float32))],valid_names=['val'],
        callbacks=[lgb.early_stopping(100),lgb.log_evaluation(200)])
    bi=model.best_iteration

    def ev(Xs,yt):
        p=model.predict(Xs,num_iteration=bi);ic=spearmanr(p,yt)[0]
        o=np.argsort(p);n=len(o)
        return {'ic':round(ic,4),'d1':round(np.mean(yt[o[:n//10]]),2),
                'd10':round(np.mean(yt[o[-n//10:]]),2),'spread':round(np.mean(yt[o[-n//10:]])-np.mean(yt[o[:n//10]]),2)}
    tr,va,te=ev(norm(X_tr),y_tr),ev(norm(X_va),y_va),ev(norm(X_te),y_te)
    print(f"\n{'指标':<16} {'训练':>8} {'验证':>8} {'测试':>8}\n{'─'*40}")
    for k in ['ic','spread']:print(f"{k:<16} {tr[k]:>8} {va[k]:>8} {te[k]:>8}")

    model.save_model(str(MODEL_DIR/'lgb_reg_model.txt'))
    # 保存标准化统计量
    with open(MODEL_DIR/'v6_norm_stats.json','w') as f:json.dump(ns,f,indent=2)
    print(f"\n💾 20d保存 ({bi}棵, IC={te['ic']})")
    print(f"⏱ {time.time()-t0:.0f}s")

if __name__=='__main__':main()
