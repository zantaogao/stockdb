"""LightGBM 10日回归 v3 — 120天窗口 + 完整特征 + v2强正则
v1: FEAT_WIN=120, 30dim, 306树, IC=0.252 (过拟合早停)
v2: FEAT_WIN=60, 27dim, 1560树, IC=0.243 (太短丢信号)
v3: FEAT_WIN=120, 30dim完整, v2正则参数, 看能不能兼顾
"""
import os, json, gzip, pickle, time, numpy as np
import lightgbm as lgb
import duckdb
from pathlib import Path
from scipy import stats

BASE = Path('C:/Users/pumma/factor_lib')
DB = BASE / 'stock.db'
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'
OUT_MODEL = BASE / 'lgb_reg_10d_v3.txt'
OUT_STATS = BASE / 'v10_v3_stats.json'
OUT_RESULTS = BASE / 'train_10d_v3_results.json'

FEAT_WIN = 120
FWD_DAYS = 10
GTJA_4 = ['gtja_006', 'gtja_083', 'gtja_177', 'gtja_184']
FEAT_NAMES = [
    'chg5','chg10','chg20','chg60','chg120',
    'd5','d10','d20','d60','d120',
    'bull1','bull2','rr','std20','vr','pos',
    'nh','vpc','c1d','c3d','ep','bp','ln_cap',
    'ex5','ex10','ex20',
]
N_BASE = len(FEAT_NAMES)  # 26
N_DIMS = N_BASE + 4       # 30

def compute_features(c_arr, a_arr, r_arr, idx_c):
    c = np.array(c_arr); lc = c[-1]
    chg5=lc/c[-5]-1; chg10=lc/c[-10]-1; chg20=lc/c[-20]-1
    chg60=lc/c[-60]-1; chg120=lc/c[0]-1
    ma5=np.mean(c[-5:]); ma10=np.mean(c[-10:]); ma20=np.mean(c[-20:]); ma60=np.mean(c[-60:])
    d5=lc/ma5-1; d10=lc/ma10-1; d20=lc/ma20-1; d60=lc/ma60-1; d120=lc/np.mean(c)-1
    b1=1 if ma5>ma10>ma20 else 0; b2=1 if ma20>ma60 else 0
    rn=np.max(c[-20:])-np.min(c[-20:])
    rr=rn/np.min(c[-20:])*100 if np.min(c[-20:])>0 else 0
    std20=np.std(c[-20:])/np.mean(c[-20:])*100
    vols=np.array(a_arr[-20:])
    vr=vols[-1]/np.mean(vols) if np.mean(vols)>0 else 1
    rl,rh=np.min(c[-20:]),np.max(c[-20:])
    pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
    nh=1 if lc>rh*0.97 else 0; vpc=1 if chg5>0 and vr>1.2 else 0
    c1d=r_arr[-1] if len(r_arr)>0 else 0
    c3d=lc/c[-3]-1 if len(c)>=3 else 0
    if idx_c is not None and len(idx_c) >= 20:
        ex5 = chg5 - (idx_c[-1]/idx_c[-5]-1)
        ex10 = chg10 - (idx_c[-1]/idx_c[-10]-1)
        ex20 = chg20 - (idx_c[-1]/idx_c[-20]-1)
    else: ex5 = ex10 = ex20 = 0.0
    return np.array([chg5,chg10,chg20,chg60,chg120,
        d5,d10,d20,d60,d120,
        b1,b2,rr,std20,vr,pos,nh,vpc,c1d,c3d,0.5,0.5,22.0,
        ex5,ex10,ex20], dtype=np.float32)

def build_gtja_lookup(gtja_dict, gn):
    if gn not in gtja_dict: return None, None
    df = gtja_dict[gn]; dates = sorted([str(d)[:10] for d in df.index])
    return dates, df

def get_gtja_value_fast(code, date_str, gtja_lookup):
    dates, df = gtja_lookup
    if dates is None: return 0.0
    import bisect
    idx = bisect.bisect_right(dates, date_str) - 1
    if idx >= 0:
        d = dates[idx]
        if code in df.columns:
            val = df.loc[d, code]
            return float(val) if not np.isnan(val) else 0.0
    return 0.0

def main():
    t0 = time.time()
    print("Training 10d v3 model (120d window, 30dim, v2 reg)", flush=True)
    print("="*60, flush=True)

    with gzip.open(GTJA_PKL, 'rb') as f: gtja = pickle.load(f)
    gtja_lookups = {gn: build_gtja_lookup(gtja, gn) for gn in GTJA_4}
    conn = duckdb.connect(str(DB), read_only=True)
    stock_codes = [r[0] for r in conn.execute(
        "SELECT DISTINCT stock_code FROM stock_daily ORDER BY stock_code").fetchall()]
    print(f"Stocks: {len(stock_codes)}", flush=True)

    X_list, y_list = [], []
    for ci, code in enumerate(stock_codes):
        rows = conn.execute(f"""
            SELECT date, close, COALESCE(change_pct,0), volume
            FROM stock_daily WHERE stock_code='{code}'
            AND date >= '2020-01-01' ORDER BY date
        """).fetchall()
        if len(rows) < FEAT_WIN + FWD_DAYS + 10: continue

        c_arr = [float(r[1]) for r in rows]
        r_arr = [float(r[2])/100 for r in rows]
        a_arr = [float(r[3]) if r[3] else 0 for r in rows]
        dates = [str(r[0])[:10] for r in rows]

        first_date, last_date = dates[0], dates[-1]
        idx_rows = conn.execute(f"SELECT date,close FROM index_daily WHERE index_code='000001' AND date>='{first_date}' ORDER BY date").fetchall()
        idx_map = {str(r[0])[:10]: float(r[1]) for r in idx_rows}
        idx_c_arr = []
        for d in dates:
            val = idx_map.get(d)
            if val is not None: idx_c_arr.append(val)
            elif idx_c_arr: idx_c_arr.append(idx_c_arr[-1])
            else: idx_c_arr.append(0)

        for i in range(FEAT_WIN, len(rows) - FWD_DAYS):
            idx_win = np.array(idx_c_arr[i-FEAT_WIN:i+1]) if len(idx_c_arr) >= i+1 else None
            feat = compute_features(c_arr[i-FEAT_WIN:i+1], a_arr[i-FEAT_WIN:i+1], r_arr[i-FEAT_WIN:i+1], idx_win)
            gtja_v = [get_gtja_value_fast(code, dates[i], gtja_lookups[gn]) for gn in GTJA_4]
            X_list.append(np.append(feat, np.array(gtja_v, dtype=np.float32)))
            fc = c_arr[i+FWD_DAYS] if i+FWD_DAYS < len(c_arr) else c_arr[-1]
            y_list.append(fc / c_arr[i] - 1)

        if (ci+1) % 500 == 0:
            print(f"  {ci+1}/{len(stock_codes)} stocks, {len(X_list)} samples", flush=True)

    conn.close()
    X_raw = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.float32)
    print(f"\nTotal samples: {len(X_raw)}", flush=True)
    print(f"Label stats: mean={np.mean(y)*100:+.2f}% std={np.std(y)*100:.2f}%", flush=True)

    n, n_train = len(X_raw), int(len(X_raw)*0.8)
    X_train, y_train = X_raw[:n_train], y[:n_train]
    X_val, y_val = X_raw[n_train:], y[n_train:]
    print(f"Train: {n_train:,}  Val: {len(X_val):,}", flush=True)

    new_stats = {}
    for j in range(N_DIMS):
        vals = X_raw[:, j]; valid = vals[~np.isnan(vals)]
        if len(valid) > 0:
            new_stats[f'feat_{j}'] = {
                'mean': float(np.mean(valid)), 'std': float(np.std(valid)),
                'low': float(np.percentile(valid, 1)), 'high': float(np.percentile(valid, 99))
            }

    def normalize(X, stats):
        Xn = X.copy()
        for j in range(N_DIMS):
            key = f'feat_{j}'
            if key in stats and stats[key]['std'] > 0:
                s = stats[key]
                Xn[:, j] = np.clip(Xn[:, j], s['low'], s['high'])
                Xn[:, j] = (Xn[:, j] - s['mean']) / s['std']
        return np.nan_to_num(Xn, nan=0.0)

    X_train_n, X_val_n = normalize(X_train, new_stats), normalize(X_val, new_stats)
    dtrain = lgb.Dataset(X_train_n, y_train)
    dval = lgb.Dataset(X_val_n, y_val, reference=dtrain)

    print("\nTraining LightGBM...", flush=True)
    params = {
        'objective': 'regression', 'metric': 'l2',
        'num_leaves': 31,
        'learning_rate': 0.01,
        'feature_fraction': 0.7,
        'bagging_fraction': 0.7,
        'bagging_freq': 5,
        'min_data_in_leaf': 200,
        'lambda_l1': 0.1,
        'lambda_l2': 1.0,
        'verbose': 1, 'num_threads': 6,
        'max_depth': 6,
        'device': 'gpu',
        'min_gain_to_split': 0.1,
    }
    model = lgb.train(params, dtrain, num_boost_round=3000,
                      valid_sets=[dtrain, dval], valid_names=['train','val'],
                      callbacks=[lgb.early_stopping(30), lgb.log_evaluation(100)])

    pred_train, pred_val = model.predict(X_train_n), model.predict(X_val_n)
    ic_train = stats.spearmanr(pred_train, y_train)[0]
    ic_val = stats.spearmanr(pred_val, y_val)[0]

    print(f"\n{'='*60}", flush=True)
    print(f"10-Day v3 Model Results", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"Trees: {model.num_trees()}", flush=True)
    print(f"Features: {model.num_feature()}", flush=True)
    print(f"FEAT_WIN: {FEAT_WIN}", flush=True)
    print(f"Train IC: {ic_train:.4f}", flush=True)
    print(f"Val IC:   {ic_val:.4f}", flush=True)

    val_arr = np.array(list(zip(pred_val, y_val)))
    val_arr = val_arr[val_arr[:,0].argsort()]
    d10 = len(val_arr)//10
    print("Decile returns (val):", flush=True)
    for d in range(10):
        s,e = d*d10, (d+1)*d10 if d<9 else len(val_arr)
        print(f"  D{d+1}: {np.mean(val_arr[s:e,1])*100:+.2f}%", flush=True)
    spread = (np.mean(val_arr[-d10:,1])-np.mean(val_arr[:d10,1]))*100
    print(f"  Spread: {spread:+.2f}%", flush=True)

    imp = model.feature_importance(importance_type='gain')
    top10 = np.argsort(imp)[-10:][::-1]
    print("Top 10 features (gain):", flush=True)
    for j in top10:
        name = FEAT_NAMES[j] if j < N_BASE else f'gtja_{j-N_BASE}'
        print(f"  feat_{j} ({name}): {imp[j]:.1f}", flush=True)

    model.save_model(str(OUT_MODEL))
    with open(OUT_STATS, 'w') as f: json.dump(new_stats, f)
    with open(OUT_RESULTS, 'w') as f:
        json.dump({
            'ic_train': ic_train, 'ic_val': ic_val,
            'spread': spread, 'trees': model.num_trees(),
            'feat_win': FEAT_WIN, 'n_dims': N_DIMS,
            'time': time.time()-t0
        }, f, indent=2)

    print(f"\nSaved: {OUT_MODEL}", flush=True)
    print(f"Saved: {OUT_STATS}", flush=True)
    print(f"Time: {time.time()-t0:.0f}s", flush=True)

if __name__ == '__main__': main()
