#!/usr/bin/env python3
"""cls27 分类模型重训 — 38基础+4GTJA=42维，标签: 20日>5%"""
import json, os, sys, time, math
import numpy as np
import lightgbm as lgb
from pathlib import Path
from scipy.stats import spearmanr, skew, kurtosis

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).parent.parent))
import duckdb

BASE = Path.home() / '.hermes' / 'stockdb'
MODEL_DIR = BASE / 'models'
DB_PATH = BASE / 'stock.db'
FWD_DAYS = 20
THRESHOLD = 5.0  # 20日涨超5%
SPLIT_TRAIN = '2024-06-01'
SPLIT_VAL = '2025-01-01'
N_BASE = 38
N_GTJA = 4
N_FEATS = N_BASE + N_GTJA


def main():
    t0 = time.time()
    print("="*65)
    print(f"📊 cls27 分类重训 — {N_FEATS}维, 阈值>{THRESHOLD}%")
    print(f"  切分: {SPLIT_TRAIN}/{SPLIT_VAL}")
    print("="*65)

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    stocks = [r[0] for r in conn.execute("""
        SELECT stock_code FROM stock_info WHERE stock_code NOT LIKE '8%'
        AND stock_code NOT LIKE '4%' AND board != '北交所'
        AND (stock_name NOT LIKE '%ST%' OR stock_name IS NULL) ORDER BY stock_code
    """).fetchall()]
    print(f"\n📡 股票: {len(stocks)}")

    # GTJA
    gtja_compact, gtja_names = None, []
    cp = MODEL_DIR / 'gtja_compact.pkl'
    if cp.exists():
        import pickle
        with open(cp, 'rb') as f: gtja_compact = pickle.load(f)
        gtja_names = sorted(gtja_compact.keys())[:N_GTJA]
        print(f"  GTJA: {N_GTJA}因子")

    vm_rows = conn.execute("""
        SELECT stock_code, date, pe_ttm, pb, total_mv FROM stock_valuation ORDER BY stock_code, date
    """).fetchall()
    vm = {}
    for code, dt, pe, pb, mv in vm_rows:
        e = {}
        if pe and float(pe) > 0: e['ep'] = 1.0/float(pe)
        if pb and float(pb) > 0: e['bp'] = 1.0/float(pb)
        if mv and float(mv) > 0: e['ln_cap'] = np.log(float(mv))
        if e: vm[(code, str(dt)[:10])] = e
    print(f"  估值: {len(vm)}")

    print("📡 行情...")
    all_c = conn.execute("""
        SELECT stock_code, date, close, volume FROM stock_daily ORDER BY stock_code, date
    """).fetchall()
    sd = {}
    for code, dt, close, vol in all_c:
        sd.setdefault(code, []).append((str(dt)[:10], float(close), float(vol or 0)))
    conn.close()

    L = 120; total = len(stocks)
    Xa, ya, Da = [], [], []

    for si, code in enumerate(stocks):
        r = sd.get(code, [])
        if len(r) < L + FWD_DAYS + 1: continue
        dt_list = [x[0] for x in r]
        c = np.array([x[1] for x in r])
        n = len(c)
        p = np.zeros(n); p[1:] = (c[1:]-c[:-1])/c[:-1]

        gtja_s = {}
        if gtja_compact:
            for gn in gtja_names:
                gtja_s[gn] = gtja_compact.get(gn, {}).get(code, {})

        ns = n - L - FWD_DAYS
        F = np.zeros((ns, N_FEATS), dtype=np.float32)

        for j in range(ns):
            i = j + L
            dt = dt_list[i]
            w = c[i-L+1:i+1]; lc = w[-1]
            p20 = p[i-19:i+1]; p60 = p[i-59:i+1]

            # 38维（与40d相同公式）
            chg5=lc/w[-5]-1; chg10=lc/w[-10]-1; chg20=lc/w[-20]-1
            chg60=lc/w[-60]-1; chg120=lc/w[0]-1
            m5=np.mean(w[-5:]); m10=np.mean(w[-10:]); m20=np.mean(w[-20:])
            m60=np.mean(w[-60:]); m120=np.mean(w)
            d5=lc/m5-1; d10=lc/m10-1; d20=lc/m20-1; d60=lc/m60-1; d120=lc/m120-1
            b1=1. if m5>m10>m20 else 0.; b2=1. if m20>m60 else 0.
            w20=w[-20:]; rl,rh=np.min(w20),np.max(w20)
            rr=(rh-rl)/rl*100 if rl>0 else 0
            s20=np.std(w20)/np.mean(w20)*100 if np.mean(w20)>0 else 0
            pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50.
            nh=1. if lc>rh*.97 else 0.; c1d=p[-1]
            c3d=lc/w[-3]-1 if len(w)>=3 and w[-3]>0 else 0
            ve=vm.get((code,dt),{})
            ep=ve.get('ep',.5); bp=ve.get('bp',.5); lnc=ve.get('ln_cap',22.)
            ex5=0.; ex10=0.; ex20=0.
            w20c=w[-20:]; sk20=float(skew(w20c)) if len(w20c)>=20 else 0
            ku20=float(kurtosis(w20c,fisher=False)) if len(w20c)>=20 else 3
            signs=np.sign(p20)
            dn=0
            for s in reversed(signs):
                if s<0: dn+=1
                else: break
            ur10=np.sum(signs[-10:]>0)/10. if len(signs)>=10 else .5
            if len(p60)>=40:
                vo=np.std(p60[:20])*math.sqrt(252); vn=np.std(p60[-20:])*math.sqrt(252)
                vc=vn/vo-1 if vo>0 else 0
            else: vc=0
            rs=chg5-(m20/m60-1) if m60>0 else 0
            ku60=float(kurtosis(w[-60:],fisher=False)) if len(w)>=60 else 3
            if len(w20)>=10:
                x5=np.arange(5); y5=w20[-5:]
                sl5=float(np.sum((x5-x5.mean())*(y5-y5.mean()))/np.sum((x5-x5.mean())**2)) if np.sum((x5-x5.mean())**2)>0 else 0
                x10=np.arange(10); y10=w20[-10:]
                sl10=float(np.sum((x10-x10.mean())*(y10-y10.mean()))/np.sum((x10-x10.mean())**2)) if np.sum((x10-x10.mean())**2)>0 else 0
                ac=sl5-sl10
            else: sl5=sl10=ac=0
            vols20=[x[2] for x in r[max(0,i-19):i+1]]
            vr20=vols20[-1]/np.mean(vols20) if np.mean(vols20)>0 else 1.
            vs=1. if chg5<-.01 and vr20<.7 else 0.
            vd=1. if (chg5>0 and vr20<.8) or (chg5<0 and vr20>1.2) else 0.

            feat38 = np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
                b1,b2,rr,s20,1.,pos,nh,0.,c1d,c3d,ep,bp,lnc,ex5,ex10,ex20,
                sk20,ku20,dn,ur10,vc,rs,ku60,sl5,sl10,ac,vs,vd], dtype=np.float64)
            F[j,:38] = np.nan_to_num(feat38, nan=0.0)

            for gi, gn in enumerate(gtja_names):
                val = gtja_s.get(gn, {}).get(dt, 0.)
                if val == 0. and gtja_s.get(gn):
                    from datetime import datetime, timedelta
                    for o in range(1,16):
                        pd=(datetime.strptime(dt,'%Y-%m-%d')-timedelta(days=o)).strftime('%Y-%m-%d')
                        if pd in gtja_s[gn]: val=gtja_s[gn][pd]; break
                F[j,N_BASE+gi]=val

        # 标签：20日涨超THRESHOLD%
        for j in range(ns):
            i=j+L
            fwd_ret=(c[i+FWD_DAYS]/c[i]-1)*100
            ya.append(1 if fwd_ret>THRESHOLD else 0)
            Da.append(dt_list[i])
        Xa.append(F[:ns])

        if (si+1)%500==0:
            print(f"  [{si+1}/{total}] {sum(len(x) for x in Xa):,} 样本  {time.time()-t0:.0f}s", flush=True)

    if not Xa: return
    X=np.concatenate(Xa); y=np.array(ya)
    print(f"\n总样本: {len(X):,}  正样本率: {y.mean()*100:.1f}%")
    Da=np.array(Da)
    m_tr=Da<SPLIT_TRAIN; m_va=(Da>=SPLIT_TRAIN)&(Da<SPLIT_VAL); m_te=Da>=SPLIT_VAL
    X_tr,y_tr=X[m_tr],y[m_tr]; X_va,y_va=X[m_va],y[m_va]; X_te,y_te=X[m_te],y[m_te]
    print(f"  训练: {len(X_tr):,}  验证: {len(X_va):,}  测试: {len(X_te):,}")

    ns={}
    for j in range(N_FEATS):
        v=X_tr[:,j]; v=v[~np.isnan(v)&~np.isinf(v)]
        if len(v)<100: continue
        lo,hi=float(np.percentile(v,.5)),float(np.percentile(v,99.5))
        ns[f'feat_{j}']={'mean':float(np.mean(v)),'std':float(np.std(v,ddof=1)),'low':lo,'high':hi}

    def norm(Xi):
        Xo=Xi.copy()
        for j in range(N_FEATS):
            k=f'feat_{j}'
            if k in ns and ns[k]['std']>0:
                s=ns[k]; Xo[:,j]=np.clip(Xo[:,j],s['low'],s['high']); Xo[:,j]=(Xo[:,j]-s['mean'])/s['std']
        return Xo

    print("\n🏋️ 训练分类...")
    model=lgb.train({'objective':'binary','metric':'auc','learning_rate':0.02,
        'num_leaves':63,'max_depth':8,'feature_fraction':0.7,'bagging_fraction':0.8,
        'bagging_freq':5,'min_data_in_leaf':50,'num_threads':8,'verbosity':-1,'seed':42,
        'class_weight':'balanced'},
        lgb.Dataset(norm(X_tr),y_tr), num_boost_round=3000,
        valid_sets=[lgb.Dataset(norm(X_va),y_va)],valid_names=['val'],
        callbacks=[lgb.early_stopping(50),lgb.log_evaluation(200)])
    bi=model.best_iteration

    def ev(Xs,yt):
        p=model.predict(Xs,num_iteration=bi)
        from sklearn.metrics import roc_auc_score, accuracy_score
        auc=roc_auc_score(yt,p)
        acc=accuracy_score(yt,p>.5)
        return {'auc':round(auc,4),'acc':round(acc,4)}

    tr,va,te=ev(norm(X_tr),y_tr),ev(norm(X_va),y_va),ev(norm(X_te),y_te)
    print(f"\n{'指标':<16} {'训练':>8} {'验证':>8} {'测试':>8}\n{'─'*40}")
    for k in ['auc','acc']: print(f"{k:<16} {tr[k]:>8} {va[k]:>8} {te[k]:>8}")

    model.save_model(str(MODEL_DIR/'lgb_cls_model.txt'))
    print(f"\n💾 cls27保存 ({bi}棵, AUC={te['auc']})")
    print(f"⏱ {time.time()-t0:.0f}s")

if __name__ == '__main__':
    main()
