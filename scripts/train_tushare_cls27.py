"""Train LightGBM classification (cls27) — ternary label.
Data source: tushare.db (DuckDB).

Features (27): 23 technical/fundamental + 4 GTJA
Label: 3-class based on 40-day forward return
  0: below 33rd percentile (bottom)
  1: middle (33rd-67th)
  2: above 67th percentile (top)
"""
import os, json, gzip, pickle, time, sys, numpy as np
import lightgbm as lgb
import duckdb
from pathlib import Path
from scipy import stats
import bisect

sys.stdout.reconfigure(line_buffering=True)

# === Config ===
BASE = Path('/Users/zantao/.hermes/stockdb')
DB = Path('/Users/zantao/.hermes/stockdb/tushare.db')
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'
OUT_MODEL = BASE / 'lgb_cls_tushare.txt'
OUT_STATS = BASE / 'cls27_norm_stats_tushare.json'

FEAT_WIN = 120
FWD_DAYS = 40
GTJA_4 = ['gtja_006', 'gtja_083', 'gtja_177', 'gtja_184']

FEAT_NAMES = [
    'chg5','chg10','chg20','chg60','chg120',
    'd5','d10','d20','d60','d120',
    'bull1','bull2','rr','std20','vr','pos',
    'nh','vpc','c1d','c3d','ep','bp','ln_cap',
]


def compute_features(c_arr, a_arr, r_arr, v):
    c = np.array(c_arr); lc = c[-1]
    chg5=lc/c[-5]-1; chg10=lc/c[-10]-1; chg20=lc/c[-20]-1
    chg60=lc/c[-60]-1; chg120=lc/c[0]-1
    ma5=np.mean(c[-5:]); ma10=np.mean(c[-10:])
    ma20=np.mean(c[-20:]); ma60=np.mean(c[-60:])
    d5=lc/ma5-1; d10=lc/ma10-1; d20=lc/ma20-1
    d60=lc/ma60-1; d120=lc/np.mean(c)-1
    b1=1 if ma5>ma10>ma20 else 0
    b2=1 if ma20>ma60 else 0
    rn=np.max(c[-20:])-np.min(c[-20:])
    rr=rn/np.min(c[-20:])*100 if np.min(c[-20:])>0 else 0
    std20=np.std(c[-20:])/np.mean(c[-20:])*100
    vols=np.array(a_arr[-20:])
    vr=vols[-1]/np.mean(vols) if np.mean(vols)>0 else 1
    rl,rh=np.min(c[-20:]),np.max(c[-20:])
    pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
    nh=1 if lc>rh*0.97 else 0
    vpc=1 if chg5>0 and vr>1.2 else 0
    c1d=r_arr[-1] if len(r_arr)>0 else 0
    c3d=lc/c[-3]-1 if len(c)>=3 else 0
    ep=v.get('ep',0.5); bp=v.get('bp',0.5); ln_cap=v.get('ln_cap',22.0)
    return np.array([chg5,chg10,chg20,chg60,chg120,
                     d5,d10,d20,d60,d120,
                     b1,b2,rr,std20,vr,pos,
                     nh,vpc,c1d,c3d,ep,bp,ln_cap], dtype=np.float32)


def build_gtja_lookup(gtja_dict, gn):
    if gn not in gtja_dict:
        return None, None
    df = gtja_dict[gn]
    dates = [str(d)[:10] for d in sorted(df.index)]
    return dates, df


def get_gtja_value_fast(code, date_str, gtja_lookup):
    dates, df = gtja_lookup
    if dates is None:
        return 0.0
    idx = bisect.bisect_right(dates, date_str[:10]) - 1
    if idx >= 0:
        d = dates[idx]
        if code in df.columns:
            val = df.loc[d, code]
            return float(val) if not np.isnan(val) else 0.0
    return 0.0


def main():
    t0 = time.time()
    print(f"Training cls27 from tushare.db (3-class, lr=0.03)")
    print("=" * 60)

    # Load GTJA
    print("Loading GTJA...")
    with gzip.open(GTJA_PKL, 'rb') as f:
        gtja = pickle.load(f)
    gtja_lookups = {gn: build_gtja_lookup(gtja, gn) for gn in GTJA_4}

    conn = duckdb.connect(str(DB), read_only=True)

    # Valuation
    vd = {}
    val_rows = conn.execute("""
        SELECT ts_code, trade_date, pe_ttm, pb, total_mv
        FROM daily_basic ORDER BY ts_code, trade_date
    """).fetchall()
    for code, dt, pe, pb, mv in val_rows:
        v = {}
        if pe and pe > 0: v['ep'] = 1.0 / float(pe)
        if pb and pb > 0: v['bp'] = 1.0 / float(pb)
        if mv and mv > 0: v['ln_cap'] = np.log(float(mv))
        if v:
            vd[(code, dt)] = v
    print(f"  Valuation entries: {len(vd):,}")

    # Adj factor
    af = {}
    rows = conn.execute("SELECT stock_code, date, adj_factor FROM adj_factor").fetchall()
    for code, dt, af_val in rows:
        if af_val and af_val > 0:
            af[(code, dt)] = float(af_val)

    # Top stocks by volume (last 2 years)
    top_codes = [r[0] for r in conn.execute("""
        SELECT ts_code FROM (
            SELECT ts_code, SUM(vol) as total_vol
            FROM daily WHERE trade_date >= '20240101'
            GROUP BY ts_code ORDER BY total_vol DESC LIMIT 800
        ) t
    """).fetchall()]
    print(f"Top stocks by volume: {len(top_codes)}")

    # === Build panel ===
    X_list, y_raw_list = [], []
    min_rows = FEAT_WIN + FWD_DAYS + 10

    for ci, code in enumerate(top_codes):
        rows = conn.execute(f"""
            SELECT d.trade_date, d.close, COALESCE(d.pct_chg, 0), d.vol,
                   af.adj_factor
            FROM daily d
            LEFT JOIN adj_factor af ON d.stock_code = af.stock_code AND d.date = af.date
            WHERE d.ts_code = '{code}'
            AND d.trade_date >= '20200101'
            ORDER BY d.trade_date
        """).fetchall()

        if len(rows) < min_rows:
            continue

        c_arr = [float(r[1]) for r in rows]
        r_arr = [float(r[2]) / 100 for r in rows]
        a_arr = [float(r[3]) if r[3] else 0 for r in rows]
        dates = [str(r[0]) for r in rows]
        adj_factors = [float(r[4]) if r[4] else 1.0 for r in rows]

        for i in range(FEAT_WIN, len(rows) - FWD_DAYS):
            dt = dates[i]
            v = vd.get((code, dt), {})
            feat = compute_features(
                c_arr[i - FEAT_WIN:i + 1],
                a_arr[i - FEAT_WIN:i + 1],
                r_arr[i - FEAT_WIN:i + 1],
                v
            )

            # Forward return
            target_idx = i + FWD_DAYS
            if target_idx < len(rows):
                adj_today = adj_factors[i]
                adj_target = adj_factors[target_idx]
                if adj_today > 0 and adj_target > 0:
                    fwd_close = c_arr[target_idx] * (adj_today / adj_target)
                else:
                    fwd_close = c_arr[target_idx]
                ret = (fwd_close / c_arr[i] - 1) * 100
            else:
                continue

            gtja_v = [get_gtja_value_fast(code, dt, gtja_lookups[gn]) for gn in GTJA_4]
            feat_full = np.append(feat, np.array(gtja_v, dtype=np.float32))
            X_list.append(feat_full)
            y_raw_list.append(ret)

        if (ci + 1) % 100 == 0:
            print(f"  {ci+1}/{len(top_codes)} stocks, {len(X_list):,} samples [{time.time()-t0:.0f}s]")

    conn.close()

    X_raw = np.array(X_list, dtype=np.float32)
    y_raw = np.array(y_raw_list, dtype=np.float32)
    print(f"\nTotal samples: {len(X_raw):,}")
    print(f"Return stats: mean={np.mean(y_raw):+.2f}% std={np.std(y_raw):.2f}%")

    # === Ternary label ===
    # Use global percentiles across ALL data
    p33 = np.percentile(y_raw, 33)
    p67 = np.percentile(y_raw, 67)
    print(f"Label thresholds: P33={p33:+.2f}%, P67={p67:+.2f}%")

    y = np.zeros(len(y_raw), dtype=int)
    y[y_raw < p33] = 0  # bottom
    y[(y_raw >= p33) & (y_raw <= p67)] = 1  # middle
    y[y_raw > p67] = 2  # top

    class_counts = {c: int(np.sum(y == c)) for c in [0, 1, 2]}
    print(f"Class distribution: {class_counts}")
    print(f"  Class 0 (bottom < {p33:+.1f}%): {class_counts[0]:,} ({class_counts[0]/len(y)*100:.1f}%)")
    print(f"  Class 1 (middle {p33:+.1f}-{p67:+.1f}%): {class_counts[1]:,} ({class_counts[1]/len(y)*100:.1f}%)")
    print(f"  Class 2 (top > {p67:+.1f}%): {class_counts[2]:,} ({class_counts[2]/len(y)*100:.1f}%)")

    # Random 80/20 split
    np.random.seed(42)
    n = len(X_raw)
    idx = np.random.permutation(n)
    n_train = int(n * 0.8)
    X_train_raw, y_train = X_raw[idx[:n_train]], y[idx[:n_train]]
    X_val_raw, y_val = X_raw[idx[n_train:]], y[idx[n_train:]]
    print(f"\nTrain: {len(X_train_raw):,}, Val: {len(X_val_raw):,}")

    # Normalize
    new_stats = {}
    for j in range(23):
        vals = X_train_raw[:, j]
        valid = vals[~np.isnan(vals)]
        if len(valid) > 0:
            new_stats[f'feat_{j}'] = {
                'mean': float(np.mean(valid)),
                'std': float(np.std(valid)),
                'low': float(np.percentile(valid, 1)),
                'high': float(np.percentile(valid, 99))
            }

    def normalize(X, stats):
        Xn = X.copy()
        for j in range(23):
            key = f'feat_{j}'
            if key in stats and stats[key]['std'] > 0:
                s = stats[key]
                Xn[:, j] = np.clip(Xn[:, j], s['low'], s['high'])
                Xn[:, j] = (Xn[:, j] - s['mean']) / s['std']
        return np.nan_to_num(Xn, nan=0.0)

    X_train = normalize(X_train_raw, new_stats)
    X_val = normalize(X_val_raw, new_stats)

    with open(OUT_STATS, 'w') as f:
        json.dump(new_stats, f)
    print(f"Stats saved: {OUT_STATS}")

    # === Train ===
    print(f"\nTraining LightGBM classifier (lr=0.03, early_stopping=20, max 500 rounds)...")
    dtrain = lgb.Dataset(X_train, y_train)
    dval = lgb.Dataset(X_val, y_val, reference=dtrain)

    params = {
        'objective': 'multiclass',
        'num_class': 3,
        'metric': 'multi_logloss',
        'num_leaves': 63,
        'learning_rate': 0.03,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'min_data_in_leaf': 100,
        'verbose': 1,
        'num_threads': -1,
        'max_depth': 8,
        'device': 'cpu',
    }

    model = lgb.train(params, dtrain, num_boost_round=500,
                      valid_sets=[dtrain, dval], valid_names=['train', 'val'],
                      callbacks=[lgb.early_stopping(20), lgb.log_evaluation(50)])

    best_iter = model.best_iteration

    # Predict probabilities
    prob_train = model.predict(X_train, num_iteration=best_iter)
    prob_val = model.predict(X_val, num_iteration=best_iter)

    # Per-class accuracy
    pred_train_cls = np.argmax(prob_train, axis=1)
    pred_val_cls = np.argmax(prob_val, axis=1)
    acc_train = np.mean(pred_train_cls == y_train)
    acc_val = np.mean(pred_val_cls == y_val)

    # Per-class metrics
    print(f"\n{'='*60}")
    print(f"cls27 Results (3-class)")
    print(f"{'='*60}")
    print(f"Trees: {model.num_trees()}, Best: {best_iter}")
    print(f"Train accuracy: {acc_train:.4f}")
    print(f"Val accuracy:   {acc_val:.4f}")

    for c in range(3):
        mask_val = y_val == c
        if mask_val.sum() > 0:
            acc_c = np.mean(pred_val_cls[mask_val] == c)
            print(f"  Class {c} accuracy: {acc_c:.4f} ({mask_val.sum():,} samples)")

    # Top/bottom return analysis
    # Sort by class 2 probability
    prob_top = prob_val[:, 2]
    sorted_idx = np.argsort(prob_top)
    d10 = len(sorted_idx) // 10
    print(f"\nDecile analysis (by class 2 probability):")
    for d in range(10):
        s, e = d * d10, (d + 1) * d10 if d < 9 else len(sorted_idx)
        batch = sorted_idx[s:e]
        avg_ret = np.mean(y_raw[batch])
        avg_prob = np.mean(prob_top[batch])
        cls_dist = [np.mean(y_val[batch] == c) for c in range(3)]
        print(f"  D{d+1}: ret={avg_ret:+.2f}% prob={avg_prob:.3f} cls=[{cls_dist[0]:.2f},{cls_dist[1]:.2f},{cls_dist[2]:.2f}]")

    spread = np.mean(y_raw[sorted_idx[-d10:]]) - np.mean(y_raw[sorted_idx[:d10]])
    print(f"  Spread: {spread:+.1f}%")

    # Feature importance
    imp = model.feature_importance(importance_type='gain')
    top10 = np.argsort(imp)[-10:][::-1]
    total_imp = sum(imp)
    print("\nTop 10 features:")
    for j in top10:
        nm = FEAT_NAMES[j] if j < 23 else f'gtja_{GTJA_4[j-23]}'
        print(f"  {nm:12s}: {imp[j]/total_imp*100:5.1f}%")

    model.save_model(str(OUT_MODEL), num_iteration=best_iter)
    print(f"\nSaved: {OUT_MODEL} ({best_iter} trees, val acc={acc_val:.4f})")
    print(f"Time: {time.time()-t0:.0f}s")


if __name__ == '__main__':
    main()
