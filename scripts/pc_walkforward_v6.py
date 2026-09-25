"""Walk-Forward v6 20d训练 — 滚动窗口+早停，替代80/20单次切分
PC GPU训练，使用core/features.py 统一特征管道
"""
import os, json, gzip, pickle, time, numpy as np
import lightgbm as lgb
import duckdb
from pathlib import Path
from datetime import datetime, timedelta
from scipy import stats

BASE = Path('C:/Users/pumma/factor_lib')
DB = BASE / 'stock.db'
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'
OUT_MODEL = BASE / 'lgb_reg_wfv6.txt'
OUT_STATS = BASE / 'v6_norm_stats.json'
OUT_RESULTS = BASE / 'wf_results.json'

FEAT_WIN = 120
FWD_DAYS = 20
GTJA_4 = ['gtja_006', 'gtja_083', 'gtja_177', 'gtja_184']
FEAT_NAMES = [
    'chg5','chg10','chg20','chg60','chg120',
    'd5','d10','d20','d60','d120',
    'bull1','bull2','rr','std20','vr','pos',
    'nh','vpc','c1d','c3d','ep','bp','ln_cap',
]

def compute_features(c_arr, a_arr, r_arr):
    """23个基础特征，与 core/features.py 完全一致"""
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
    return np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
        b1,b2,rr,std20,vr,pos,nh,vpc,c1d,c3d,0.5,0.5,22.0], dtype=np.float32)

def build_gtja_lookup(gtja_dict, gn):
    if gn not in gtja_dict: return None, None
    df = gtja_dict[gn]; dates = sorted(df.index)
    return dates, df

import bisect
def get_gtja_value_fast(code, date_str, gtja_lookup):
    dates, df = gtja_lookup
    if dates is None: return 0.0
    from pandas import Timestamp
    ts = Timestamp(date_str)
    idx = bisect.bisect_right(dates, ts) - 1
    if idx >= 0:
        d = str(dates[idx])[:10]
        if code in df.columns:
            val = df.loc[d, code]
            return float(val) if not np.isnan(val) else 0.0
    return 0.0

def load_training_data(conn, stock_codes, gtja_lookups, date_start, date_end):
    """加载指定日期范围的全量训练数据"""
    X_list, y_list = [], []
    for ci, code in enumerate(stock_codes):
        rows = conn.execute(f"""
            SELECT date, close, COALESCE(change_pct,0), volume
            FROM stock_daily WHERE stock_code='{code}'
            AND date >= '{date_start}' AND date <= '{date_end}'
            ORDER BY date
        """).fetchall()
        if len(rows) < FEAT_WIN + FWD_DAYS + 5: continue
        c_arr = [float(r[1]) for r in rows]
        r_arr = [float(r[2])/100 for r in rows]
        a_arr = [float(r[3]) if r[3] else 0 for r in rows]
        dates = [str(r[0])[:10] for r in rows]
        for i in range(FEAT_WIN, len(rows) - FWD_DAYS):
            feat = compute_features(c_arr[i-FEAT_WIN:i+1], a_arr[i-FEAT_WIN:i+1], r_arr[i-FEAT_WIN:i+1])
            gtja_v = [get_gtja_value_fast(code, dates[i], gtja_lookups[gn]) for gn in GTJA_4]
            feat_full = np.append(feat, np.array(gtja_v, dtype=np.float32))
            fc = c_arr[i+FWD_DAYS] if i+FWD_DAYS < len(c_arr) else c_arr[-1]
            y_list.append((fc / c_arr[i] - 1))  # ratio format (matches v6)
            X_list.append(feat_full)
        if (ci+1) % 500 == 0:
            print(f"    {ci+1}/{len(stock_codes)} stocks, {len(X_list)} samples", flush=True)
    return np.array(X_list, dtype=np.float32), np.array(y_list, dtype=np.float32)

def main():
    t0 = time.time()
    # Load GTJA
    print("Loading GTJA...", flush=True)
    with gzip.open(GTJA_PKL, 'rb') as f: gtja = pickle.load(f)
    gtja_lookups = {gn: build_gtja_lookup(gtja, gn) for gn in GTJA_4}
    conn = duckdb.connect(str(DB), read_only=True)

    # All stock codes
    stock_codes = [r[0] for r in conn.execute(
        "SELECT DISTINCT stock_code FROM stock_daily ORDER BY stock_code").fetchall()]
    print(f"Stocks: {len(stock_codes)}", flush=True)

    # All available dates
    all_dates = [str(r[0])[:10] for r in conn.execute(
        "SELECT DISTINCT date FROM stock_daily ORDER BY date").fetchall()]
    print(f"Date range: {all_dates[0]} ~ {all_dates[-1]} ({len(all_dates)} days)", flush=True)

    # Build walk-forward windows: 12-month train, 3-month test, roll 3 months
    min_dt = datetime.strptime(all_dates[0], '%Y-%m-%d')
    max_dt = datetime.strptime(all_dates[-1], '%Y-%m-%d')
    windows = []
    cursor = min_dt + timedelta(days=365)  # start 12 months in
    while cursor + timedelta(days=90) < max_dt:
        train_start = (cursor - timedelta(days=365)).strftime('%Y-%m-%d')
        train_end = cursor.strftime('%Y-%m-%d')
        test_start = cursor.strftime('%Y-%m-%d')
        test_end = (cursor + timedelta(days=90)).strftime('%Y-%m-%d')
        windows.append({'train': (train_start, train_end), 'test': (test_start, test_end),
                        'label': f'{train_start[:7]}-{test_start[:7]}'})
        cursor += timedelta(days=90)

    print(f"Walk-forward windows: {len(windows)}", flush=True)
    for w in windows:
        print(f"  {w['label']}: train {w['train'][0]}~{w['train'][1]} test {w['test'][0]}~{w['test'][1]}", flush=True)

    # Train each fold
    fold_results = []
    best_rounds = []
    
    for fi, w in enumerate(windows):
        print(f"\n{'='*60}", flush=True)
        print(f"Fold {fi+1}/{len(windows)}: {w['label']}", flush=True)
        print(f"{'='*60}", flush=True)
        
        # Load training data
        X, y = load_training_data(conn, stock_codes, gtja_lookups, w['train'][0], w['train'][1])
        print(f"  Train samples: {len(X)}", flush=True)
        if len(X) < 10000:
            print(f"  Skip fold (too few samples)", flush=True)
            continue
        
        # Stats from this fold's training data
        fold_stats = {}
        for j in range(27):
            vals = X[:, j]
            valid = vals[~np.isnan(vals)]
            if len(valid) > 0:
                fold_stats[f'feat_{j}'] = {
                    'mean': float(np.mean(valid)), 'std': float(np.std(valid)),
                    'low': float(np.percentile(valid, 1)), 'high': float(np.percentile(valid, 99))
                }
        
        # Standardize
        X_norm = X.copy()
        for j in range(27):
            s = fold_stats.get(f'feat_{j}', {})
            if s.get('std', 0) > 0:
                X_norm[:, j] = np.clip(X_norm[:, j], s['low'], s['high'])
                X_norm[:, j] = (X_norm[:, j] - s['mean']) / s['std']
        X_norm = np.nan_to_num(X_norm, nan=0.0)
        
        # Train with validation split for early stopping
        split = int(len(X_norm) * 0.9)
        X_tr, y_tr = X_norm[:split], y[:split]
        X_vl, y_vl = X_norm[split:], y[split:]
        
        dtrain = lgb.Dataset(X_tr, y_tr)
        dval = lgb.Dataset(X_vl, y_vl, reference=dtrain)
        
        params = {
            'objective': 'regression', 'metric': 'l2',
            'num_leaves': 63, 'learning_rate': 0.03,
            'feature_fraction': 0.8, 'bagging_fraction': 0.8,
            'bagging_freq': 5, 'min_data_in_leaf': 100,
            'verbose': -1, 'num_threads': 6, 'max_depth': 8,
            'device': 'gpu'
        }
        
        model = lgb.train(params, dtrain, num_boost_round=3000,
                          valid_sets=[dtrain, dval], valid_names=['train', 'val'],
                          callbacks=[lgb.early_stopping(30), lgb.log_evaluation(200)])
        
        n_rounds = model.num_trees()
        best_rounds.append(n_rounds)
        
        # Evaluate on test window
        X_te, y_te = load_training_data(conn, stock_codes[:1000], gtja_lookups, w['test'][0], w['test'][1])
        if len(X_te) > 1000:
            X_te_norm = X_te.copy()
            for j in range(27):
                s = fold_stats.get(f'feat_{j}', {})
                if s.get('std', 0) > 0:
                    X_te_norm[:, j] = np.clip(X_te_norm[:, j], s['low'], s['high'])
                    X_te_norm[:, j] = (X_te_norm[:, j] - s['mean']) / s['std']
            X_te_norm = np.nan_to_num(X_te_norm, nan=0.0)
            pred_te = model.predict(X_te_norm)
            ic_te = stats.spearmanr(pred_te, y_te)[0]
            print(f"  Test IC: {ic_te:.4f} (n={len(y_te)})", flush=True)
        else:
            ic_te = 0
            print(f"  Test: skip (too few samples)", flush=True)
        
        fold_results.append({
            'fold': fi+1, 'label': w['label'],
            'n_train': len(X), 'n_test': len(X_te) if len(X_te) > 0 else 0,
            'n_rounds': n_rounds, 'ic_test': ic_te
        })
        print(f"  Rounds: {n_rounds}, Test IC: {ic_te:.4f}", flush=True)

    conn.close()

    # Summary
    print(f"\n{'='*60}", flush=True)
    print("Walk-Forward Summary", flush=True)
    print(f"{'='*60}", flush=True)
    for r in fold_results:
        print(f"  Fold {r['fold']} ({r['label']}): {r['n_rounds']} rounds, test IC={r['ic_test']:.4f}", flush=True)
    
    median_rounds = int(np.median(best_rounds)) if best_rounds else 2000
    print(f"\nMedian optimal rounds: {median_rounds}", flush=True)
    print(f"\nRetraining on full data with {median_rounds} rounds...", flush=True)

    # Retrain on FULL data with optimal rounds
    conn = duckdb.connect(str(DB), read_only=True)
    X_all, y_all = load_training_data(conn, stock_codes, gtja_lookups, all_dates[0], all_dates[-1])
    conn.close()
    
    print(f"Full data: {len(X_all)} samples", flush=True)
    
    # Compute full-data stats
    all_stats = {}
    for j in range(27):
        vals = X_all[:, j]
        valid = vals[~np.isnan(vals)]
        if len(valid) > 0:
            all_stats[f'feat_{j}'] = {
                'mean': float(np.mean(valid)), 'std': float(np.std(valid)),
                'low': float(np.percentile(valid, 1)), 'high': float(np.percentile(valid, 99))
            }
    
    X_fn = X_all.copy()
    for j in range(27):
        s = all_stats.get(f'feat_{j}', {})
        if s.get('std', 0) > 0:
            X_fn[:, j] = np.clip(X_fn[:, j], s['low'], s['high'])
            X_fn[:, j] = (X_fn[:, j] - s['mean']) / s['std']
    X_fn = np.nan_to_num(X_fn, nan=0.0)
    
    # Train final model
    dtrain = lgb.Dataset(X_fn, y_all)
    final_model = lgb.train({
        'objective': 'regression', 'metric': 'l2',
        'num_leaves': 63, 'learning_rate': 0.03,
        'feature_fraction': 0.8, 'bagging_fraction': 0.8,
        'bagging_freq': 5, 'min_data_in_leaf': 100,
        'verbose': 1, 'num_threads': 6, 'max_depth': 8,
        'device': 'gpu'
    }, dtrain, num_boost_round=median_rounds)
    
    # Evaluate
    pred = final_model.predict(X_fn)
    ic_full = stats.spearmanr(pred, y_all)[0] if len(pred) > 1 else 0
    print(f"Final model IC (in-sample): {ic_full:.4f}", flush=True)
    
    # Decile analysis
    arr = np.array(list(zip(pred, y_all)))
    arr = arr[arr[:,0].argsort()]
    d10 = len(arr) // 10
    print("Decile returns (full):", flush=True)
    for d in range(10):
        start, end = d*d10, (d+1)*d10 if d<9 else len(arr)
        print(f"  D{d+1}: {np.mean(arr[start:end,1])*100:+.2f}%", flush=True)
    spread = (np.mean(arr[-d10:,1]) - np.mean(arr[:d10,1])) * 100
    print(f"  Spread: {spread:+.2f}%", flush=True)
    
    # Save
    final_model.save_model(str(OUT_MODEL))
    with open(OUT_STATS, 'w') as f:
        json.dump(all_stats, f)
    with open(OUT_RESULTS, 'w') as f:
        json.dump({'fold_results': fold_results, 'median_rounds': median_rounds,
                   'final_ic': ic_full, 'final_spread': spread, 'time': time.time()-t0}, f, indent=2)
    
    print(f"\nSaved: {OUT_MODEL}", flush=True)
    print(f"Saved: {OUT_STATS}", flush=True)
    print(f"Time: {time.time()-t0:.0f}s", flush=True)

if __name__ == '__main__':
    main()
