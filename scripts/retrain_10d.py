#!/usr/bin/env python3
"""10d回归重训 — 30天窗口，26短周期特征+4GTJA=30维"""
import json,sys,time,math
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
FWD_DAYS=10;SPLIT_TRAIN='2024-06-01';SPLIT_VAL='2025-01-01'
MAX_LABEL=50.0;L=30;N_BASE=26;N_GTJA=4;N_FEATS=N_BASE+N_GTJA

def main():
    t0=time.time()
    print("="*65)
    print(f"10d回归重训 — {N_FEATS}维, 窗口{L}天")
    print("="*65)
    conn=duckdb.connect(str(DB_PATH),read_only=True)
    stocks=[r[0] for r in conn.execute("""SELECT stock_code FROM stock_info
        WHERE stock_code NOT LIKE '8%' AND stock_code NOT LIKE '4%'
        AND board!='北交所' AND (stock_name NOT LIKE '%ST%' OR stock_name IS NULL) ORDER BY stock_code""").fetchall()]
    print(f"股票:{len(stocks)}")
    gtja_c,gtja_n=None,[]
    cp=MODEL_DIR/'gtja_compact.pkl'
    if cp.exists():
        import pickle
        with open(cp,'rb') as f:gtja_c=pickle.load(f)
        gtja_n=sorted(gtja_c.keys())[:N_GTJA]
    vm_rows=conn.execute("""SELECT stock_code,date,pe_ttm,pb,total_mv FROM stock_valuation ORDER BY stock_code,date""").fetchall()
    vm={}
    for code,dt,pe,pb,mv in vm_rows:
        e={}
        if pe and float(pe)>0:e['ep']=1./float(pe)
        if pb and float(pb)>0:e['bp']=1./float(pb)
        if mv and float(mv)>0:e['ln_cap']=np.log(float(mv))
        if e:vm[(code,str(dt)[:10])]=e
    print(f"估值:{len(vm)}")
    print("行情...")
    ac=conn.execute("""SELECT stock_code,date,close,volume FROM stock_daily ORDER BY stock_code,date""").fetchall()
    sd={}
    for code,dt,close,vol in ac:
        sd.setdefault(code,[]).append((str(dt)[:10],float(close),float(vol or 0)))
    conn.close()
    total=len(stocks);Xa,ya,Da=[],[],[]
    for si,code in enumerate(stocks):
        r=sd.get(code,[])
        if len(r)<L+FWD_DAYS+1:continue
        dtl=[x[0] for x in r]
        c=np.array([x[1] for x in r]);n=len(c)
        p=np.zeros(n);p[1:]=(c[1:]-c[:-1])/c[:-1]
        gtja_s={}
        if gtja_c:
            for gn in gtja_n:gtja_s[gn]=gtja_c.get(gn,{}).get(code,{})
        ns=n-L-FWD_DAYS
        F=np.zeros((ns,N_FEATS),dtype=np.float32);Y=np.zeros(ns,dtype=np.float64)
        for j in range(ns):
            i=j+L;dt=dtl[i]
            w=c[i-L+1:i+1];lc=w[-1]
            p20=p[i-19:i+1] if i>=19 else p[:i+1]
            # 26短周期特征
            chg5=lc/w[-5]-1 if len(w)>=5 else 0;chg10=lc/w[-10]-1 if len(w)>=10 else 0;chg20=lc/w[-20]-1 if len(w)>=20 else 0
            m5=np.mean(w[-5:]) if len(w)>=5 else lc;m10=np.mean(w[-10:]) if len(w)>=10 else lc;m20=np.mean(w[-20:]) if len(w)>=20 else lc
            d5=lc/m5-1 if m5>0 else 0;d10=lc/m10-1 if m10>0 else 0;d20=lc/m20-1 if m20>0 else 0
            w20=w[-20:] if len(w)>=20 else w;m20_=np.mean(w20)
            w20c=np.array(w20);rl,rh=np.min(w20c),np.max(w20c)
            rr=(rh-rl)/rl*100 if rl>0 else 0
            s20=np.std(w20c)/np.mean(w20c)*100 if np.mean(w20c)>0 else 0
            pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50.;nh=1. if lc>rh*.97 else 0.
            c1d=p[-1];c3d=lc/w[-3]-1 if len(w)>=3 and w[-3]>0 else 0
            ve=vm.get((code,dt),{});ep=ve.get('ep',.5);bp=ve.get('bp',.5);lnc=ve.get('ln_cap',22.)
            ex5=0.;ex10=0.;ex20=0.
            # 新特征
            signs=np.sign(p20);dn=0
            for s in reversed(signs):
                if s<0:dn+=1
                else:break
            ur10=np.sum(signs[-10:]>0)/10. if len(signs)>=10 else .5
            if len(w20)>=10:
                x5=np.arange(5);y5=w[-5:]
                sl5=float(np.sum((x5-x5.mean())*(y5-y5.mean()))/np.sum((x5-x5.mean())**2)) if np.sum((x5-x5.mean())**2)>0 else 0
                x10=np.arange(10);y10=w[-10:]
                sl10=float(np.sum((x10-x10.mean())*(y10-y10.mean()))/np.sum((x10-x10.mean())**2)) if np.sum((x10-x10.mean())**2)>0 else 0
                ac=sl5-sl10
            else:sl5=sl10=ac=0
            vols20=r[-20:] if len(r)>=20 else r
            vr20=vols20[-1][2]/np.mean([x[2] for x in vols20]) if np.mean([x[2] for x in vols20])>0 else 1.
            vs=1. if chg5<-.01 and vr20<.7 else 0.;vd=1. if (chg5>0 and vr20<.8) or (chg5<0 and vr20>1.2) else 0.
            feat=np.array([chg5,chg10,chg20,d5,d10,d20,rr,s20,vr20,pos,nh,0.,c1d,c3d,ep,bp,lnc,ex5,ex10,ex20,
                           dn,ur10,ac,vs,vd],dtype=np.float64)
            F[j,:25]=np.nan_to_num(feat,nan=0.)
            # GTJA
            for gi,gn in enumerate(gtja_n):
                val=gtja_s.get(gn,{}).get(dt,0.)
                if val==0. and gtja_s.get(gn):
                    from datetime import datetime as dtt,timedelta
                    for o in range(1,16):
                        pd=(dtt.strptime(dt,'%Y-%m-%d')-timedelta(days=o)).strftime('%Y-%m-%d')
                        if pd in gtja_s[gn]:val=gtja_s[gn][pd];break
                F[j,N_BASE+gi]=val
            fwd_c=c[i+FWD_DAYS]
            Y[j]=(fwd_c/lc-1)*100.
        Xa.append(F);ya.append(Y);Da.extend([dtl[L+i] for i in range(ns)])
        if (si+1)%500==0:
            print(f"  [{si+1}/{total}] {sum(len(x) for x in Xa):,}样本 {time.time()-t0:.0f}s",flush=True)
    if not Xa:return
    X=np.concatenate(Xa);y=np.concatenate(ya)
    print(f"\n总样本:{len(X):,}")
    Da=np.array(Da)
    m_tr=Da<SPLIT_TRAIN;m_va=(Da>=SPLIT_TRAIN)&(Da<SPLIT_VAL);m_te=Da>=SPLIT_VAL
    X_tr,y_tr=X[m_tr],y[m_tr];X_va,y_va=X[m_va],y[m_va];X_te,y_te=X[m_te],y[m_te]
    mk=np.abs(y_tr)<=MAX_LABEL;X_tr,y_tr=X_tr[mk],y_tr[mk]
    print(f"训练:{len(X_tr):,} 验证:{len(X_va):,} 测试:{len(X_te):,}")
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
        'num_leaves':63,'max_depth':8,'feature_fraction':0.7,'bagging_fraction':0.8,
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
    model.save_model(str(MODEL_DIR/'lgb_reg_10d.txt'))
    print(f"\n💾 10d保存 ({bi}棵, IC={te['ic']})")
    print(f"⏱ {time.time()-t0:.0f}s")

if __name__=='__main__':main()
