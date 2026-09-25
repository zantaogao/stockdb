#!/usr/bin/env python3
"""Walk-Forward Backtest - PC Version (1080Ti)
9 folds: 24-month training -> 6-month testing, rolling 6-month advance
"""
import os, sys, json, gzip, pickle, time
import numpy as np
import lightgbm as lgb
import duckdb
from pathlib import Path
from scipy import stats as sp_stats

BASE = Path('C:/Users/pumma/factor_lib')
DB = BASE / 'stock.db'
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'
STATS_PATH = BASE / 'v6_norm_stats.json'

FEAT_WIN = 120
FWD_DAYS = 20
GTJA_4 = ['gtja_006','gtja_083','gtja_177','gtja_184']
TRAIN_STOCKS = 200
TEST_STOCKS = 100

def compute_features(c_arr, a_arr, r_arr):
    c = np.array(c_arr); lc = c[-1]
    chg5=lc/c[-5]-1; chg10=lc/c[-10]-1; chg20=lc/c[-20]-1; chg60=lc/c[-60]-1; chg120=lc/c[0]-1
    ma5=np.mean(c[-5:]); ma10=np.mean(c[-10:]); ma20=np.mean(c[-20:]); ma60=np.mean(c[-60:])
    d5=lc/ma5-1; d10=lc/ma10-1; d20=lc/ma20-1; d60=lc/ma60-1; d120=lc/np.mean(c)-1
    b1=1 if ma5>ma10>ma20 else 0; b2=1 if ma20>ma60 else 0
    rn=np.max(c[-20:])-np.min(c[-20:]); rr=rn/np.min(c[-20:])*100 if np.min(c[-20:])>0 else 0
    std20=np.std(c[-20:])/np.mean(c[-20:])*100
    vols=np.array(a_arr[-20:]); vr=vols[-1]/np.mean(vols) if np.mean(vols)>0 else 1
    rl,rh=np.min(c[-20:]),np.max(c[-20:]); pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
    nh=1 if lc>rh*0.97 else 0; vpc=1 if chg5>0 and vr>1.2 else 0
    c1d=r_arr[-1] if len(r_arr)>0 else 0; c3d=lc/c[-3]-1 if len(c)>=3 else 0
    ep=0.5; bp=0.5; ln_cap=22.0
    return np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
        b1,b2,rr,std20,vr,pos,nh,vpc,c1d,c3d,ep,bp,ln_cap], dtype=np.float32)

def standardize(feat, stats):
    for j in range(23):
        key = f'feat_{j}'
        if key in stats and stats[key]['std'] > 0:
            m, s = stats[key]['mean'], stats[key]['std']
            feat[j] = max(feat[j], stats[key]['low'])
            feat[j] = min(feat[j], stats[key]['high'])
            feat[j] = (feat[j] - m) / s
    return feat

def main():
    print("Walk-Forward Backtest (PC)")
    print("=" * 60)
    
    t_start = time.time()
    
    # Load data
    print("Loading GTJA...")
    with gzip.open(GTJA_PKL, 'rb') as f:
        gtja_data = pickle.load(f)
    
    with open(STATS_PATH) as f:
        stats = json.load(f)
    
    conn = duckdb.connect(str(DB), read_only=True)
    
    stock_codes = [r[0] for r in conn.execute(
        "SELECT DISTINCT stock_code FROM stock_daily ORDER BY stock_code LIMIT ?",
        [TRAIN_STOCKS]).fetchall()]
    print(f"Stocks: {len(stock_codes)}")
    
    folds = [
        ('2020-01-01','2021-12-31','2022-01-01','2022-12-31'),
        ('2020-07-01','2022-06-30','2022-07-01','2023-06-30'),
        ('2021-01-01','2022-12-31','2023-01-01','2023-12-31'),
        ('2021-07-01','2023-06-30','2023-07-01','2024-06-30'),
        ('2022-01-01','2023-12-31','2024-01-01','2024-12-31'),
        ('2022-07-01','2024-06-30','2024-07-01','2025-06-30'),
        ('2023-01-01','2024-12-31','2025-01-01','2025-12-31'),
    ]
    
    results = []
    for fi, (tr_s, tr_e, te_s, te_e) in enumerate(folds, 1):
        print(f"\nFold {fi}/9: train={tr_s[:7]}~{tr_e[:7]} test={te_s[:7]}~{te_e[:7]}")
        t0 = time.time()
        
        # --- Train ---
        print("  Training...", end=' ', flush=True)
        X_list, y_list = [], []
        
        for code in stock_codes[:TRAIN_STOCKS]:
            rows = conn.execute(f"""
                SELECT date, close, COALESCE(change_pct,0), volume
                FROM stock_daily WHERE stock_code='{code}'
                AND date >= '{tr_s}' AND date <= '{tr_e}' ORDER BY date
            """).fetchall()
            
            if len(rows) < FEAT_WIN + FWD_DAYS + 10:
                continue
            
            c_arr = [float(r[1]) for r in rows]
            r_arr = [float(r[2])/100 for r in rows]
            a_arr = [float(r[3]) if r[3] else 0 for r in rows]
            dates = [str(r[0])[:10] for r in rows]
            
            for i in range(FEAT_WIN, len(rows) - FWD_DAYS):
                feat = compute_features(c_arr[i-FEAT_WIN:i+1], a_arr[i-FEAT_WIN:i+1], r_arr[i-FEAT_WIN:i+1])
                
                # GTJA
                date_str = dates[i]
                gtja_v = []
                for gn in GTJA_4:
                    if gn in gtja_data:
                        df = gtja_data[gn]; best = None
                        for d in reversed(sorted(df.index)):
                            if str(d)[:10] <= date_str: best = str(d)[:10]; break
                        if best and code in df.columns:
                            val = df.loc[best, code]
                            gtja_v.append(float(val) if not np.isnan(val) else 0.0)
                        else:
                            gtja_v.append(0.0)
                    else:
                        gtja_v.append(0.0)
                
                feat = np.append(feat, np.array(gtja_v, dtype=np.float32))
                feat = standardize(feat, stats)
                feat = np.nan_to_num(feat, nan=0.0)
                
                fc = c_arr[i+FWD_DAYS] if i+FWD_DAYS < len(c_arr) else c_arr[-1]
                ret = (fc / c_arr[i] - 1) * 100
                
                X_list.append(feat)
                y_list.append(ret)
        
        if len(X_list) < 1000:
            print(f"SKIP (n={len(X_list)})")
            continue
        
        X_train = np.array(X_list, dtype=np.float32)
        y_train = np.array(y_list, dtype=np.float32)
        
        dtrain = lgb.Dataset(X_train, y_train)
        params = {
            'objective': 'regression', 'metric': 'l2',
            'num_leaves': 31, 'learning_rate': 0.05,
            'feature_fraction': 0.8, 'bagging_fraction': 0.8,
            'verbose': -1, 'num_threads': 6, 'max_depth': 6,
            'device': 'gpu'
        }
        model = lgb.train(params, dtrain, num_boost_round=200)
        t_train = time.time() - t0
        print(f"n={len(X_train)} ({t_train:.0f}s)")
        
        # --- Test ---
        print("  Testing...", end=' ', flush=True)
        preds_all, rets_all = [], []
        
        for code in stock_codes[:TEST_STOCKS]:
            rows = conn.execute(f"""
                SELECT date, close, COALESCE(change_pct,0), volume
                FROM stock_daily WHERE stock_code='{code}'
                AND date >= '{te_s}' AND date <= '{te_e}' ORDER BY date
            """).fetchall()
            
            if len(rows) < FEAT_WIN + FWD_DAYS + 10:
                continue
            
            c_arr = [float(r[1]) for r in rows]
            r_arr = [float(r[2])/100 for r in rows]
            a_arr = [float(r[3]) if r[3] else 0 for r in rows]
            dates = [str(r[0])[:10] for r in rows]
            
            for i in range(FEAT_WIN, len(rows) - FWD_DAYS):
                feat = compute_features(c_arr[i-FEAT_WIN:i+1], a_arr[i-FEAT_WIN:i+1], r_arr[i-FEAT_WIN:i+1])
                
                date_str = dates[i]
                gtja_v = []
                for gn in GTJA_4:
                    if gn in gtja_data:
                        df = gtja_data[gn]; best = None
                        for d in reversed(sorted(df.index)):
                            if str(d)[:10] <= date_str: best = str(d)[:10]; break
                        if best and code in df.columns:
                            val = df.loc[best, code]
                            gtja_v.append(float(val) if not np.isnan(val) else 0.0)
                        else:
                            gtja_v.append(0.0)
                    else:
                        gtja_v.append(0.0)
                
                feat = np.append(feat, np.array(gtja_v, dtype=np.float32))
                feat = standardize(feat, stats)
                feat = np.nan_to_num(feat, nan=0.0)
                
                pred = model.predict(feat.reshape(1,-1))[0]
                fc = c_arr[i+FWD_DAYS] if i+FWD_DAYS < len(c_arr) else c_arr[-1]
                ret = (fc / c_arr[i] - 1) * 100
                preds_all.append(pred)
                rets_all.append(ret)
        
        if len(preds_all) < 50:
            print(f"SKIP (n={len(preds_all)})")
            continue
        
        ic, _ = sp_stats.spearmanr(preds_all, rets_all)
        
        # Decile spread
        arr = np.array(list(zip(preds_all, rets_all)))
        arr = arr[arr[:,0].argsort()]
        d10 = len(arr) // 10
        d1_ret = np.mean(arr[:d10, 1])
        d10_ret = np.mean(arr[-d10:, 1])
        spread = d10_ret - d1_ret
        
        results.append({
            'fold': fi, 'ic': round(float(ic), 4),
            'spread': round(float(spread), 2),
            'train_n': len(X_train), 'test_n': len(preds_all),
            'train_start': tr_s, 'test_start': te_s
        })
        
        t_test = time.time() - t0 - t_train
        print(f"IC={ic:+.4f} spread={spread:+.1f}% n={len(preds_all)} ({t_test:.0f}s)")
    
    conn.close()
    
    # --- Summary ---
    if len(results) < 3:
        print(f"\nERROR: only {len(results)} valid folds")
        return
    
    print(f"\n{'='*70}")
    print(f"Walk-Forward Results ({len(results)} folds, {time.time()-t_start:.0f}s total)")
    print(f"{'='*70}")
    print(f"{'Fold':<6} {'IC':>8} {'Spread':>8} {'Train N':>8} {'Test N':>8}")
    print(f"{'-'*42}")
    
    ics = []
    for r in results:
        ics.append(r['ic'])
        print(f"{r['fold']:<6} {r['ic']:>+8.4f} {r['spread']:>+7.1f}% {r['train_n']:>8} {r['test_n']:>8}")
    
    avg_ic = np.mean(ics)
    std_ic = np.std(ics)
    min_ic = np.min(ics)
    max_ic = np.max(ics)
    
    print(f"{'-'*42}")
    print(f"Mean IC: {avg_ic:+.4f}  Std: {std_ic:.4f}  Min: {min_ic:+.4f}  Max: {max_ic:+.4f}")
    
    print(f"\nDiagnosis:")
    if std_ic < 0.08:
        print(f"  PASS: IC stable (std={std_ic:.3f} < 0.08)")
    else:
        print(f"  WARN: IC unstable (std={std_ic:.3f} >= 0.08)")
    
    neg_folds = sum(1 for x in ics if x <= 0)
    if neg_folds == 0:
        print(f"  PASS: all folds IC > 0")
    else:
        print(f"  WARN: {neg_folds}/{len(ics)} folds IC <= 0")
    
    if avg_ic > 0.05:
        print(f"  PASS: mean IC={avg_ic:.3f} > 0.05 (significant)")
    elif avg_ic > 0.02:
        print(f"  MARGINAL: mean IC={avg_ic:.3f} (borderline)")
    else:
        print(f"  FAIL: mean IC={avg_ic:.3f} < 0.02 (not significant)")

if __name__ == '__main__':
    main()
