"""Train LightGBM regression with 40-day forward return label.
Data source: tushare.db (DuckDB).
Time-based split: train=2018-2023, val=2024, test=2025+.

Features (27): 23 technical/fundamental + 4 GTJA
Label: 40-day forward return * 100 (percentage)
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
OUT_MODEL = BASE / 'lgb_reg_40d_tushare.txt'
OUT_STATS = BASE / 'v6_norm_stats_40d_tushare.json'

FEAT_WIN = 120  # 120 trading days lookback
FWD_DAYS = 40   # forward period
GTJA_4 = ['gtja_006', 'gtja_083', 'gtja_177', 'gtja_184']

FEAT_NAMES = [
    'chg5','chg10','chg20','chg60','chg120',   # 5: returns
    'd5','d10','d20','d60','d120',              # 5: MA deviation
    'bull1','bull2','rr','std20','vr','pos',     # 6: trend/volatility/volume
    'nh','vpc','c1d','c3d',                     # 4: breakout/volatility
    'ep','bp','ln_cap',                         # 3: valuation/market cap
]  # Total: 23 + 4 GTJA = 27


def compute_features(c_arr, a_arr, r_arr, v):
    """Compute 23 features from 120-day price/volume/return arrays + valuation dict."""
    c = np.array(c_arr); lc = c[-1]
    # Returns
    chg5=lc/c[-5]-1; chg10=lc/c[-10]-1; chg20=lc/c[-20]-1
    chg60=lc/c[-60]-1; chg120=lc/c[0]-1
    # MA deviations
    ma5=np.mean(c[-5:]); ma10=np.mean(c[-10:])
    ma20=np.mean(c[-20:]); ma60=np.mean(c[-60:])
    d5=lc/ma5-1; d10=lc/ma10-1; d20=lc/ma20-1
    d60=lc/ma60-1; d120=lc/np.mean(c)-1
    # Trend/volatility/volume
    b1=1 if ma5>ma10>ma20 else 0
    b2=1 if ma20>ma60 else 0
    rn=np.max(c[-20:])-np.min(c[-20:])
    rr=rn/np.min(c[-20:])*100 if np.min(c[-20:])>0 else 0
    std20=np.std(c[-20:])/np.mean(c[-20:])*100
    vols=np.array(a_arr[-20:])
    vr=vols[-1]/np.mean(vols) if np.mean(vols)>0 else 1
    rl,rh=np.min(c[-20:]),np.max(c[-20:])
    pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
    # Breakout/volume
    nh=1 if lc>rh*0.97 else 0
    vpc=1 if chg5>0 and vr>1.2 else 0
    # Daily change
    c1d=r_arr[-1] if len(r_arr)>0 else 0
    c3d=lc/c[-3]-1 if len(c)>=3 else 0
    # Valuation
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


def build_valuation_lookup(conn):
    """Build valuation dict from tushare daily_basic table.
    Keys: (ts_code, trade_date_str) -> {'ep': float, 'bp': float, 'ln_cap': float}
    """
    print("  Building valuation lookup from daily_basic...")
    vd = {}
    # pe_ttm, pb, total_mv from daily_basic
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
    return vd


def build_adj_factor_lookup(conn):
    """Build adj_factor lookup: (ts_code, trade_date) -> adj_factor.
    We use this to compute forward-adjusted prices.
    """
    print("  Building adj_factor lookup...")
    af = {}
    rows = conn.execute("SELECT ts_code, trade_date, adj_factor FROM adj_factor").fetchall()
    for code, dt, af_val in rows:
        if af_val and af_val > 0:
            af[(code, dt)] = float(af_val)
    return af


def main():
    t0 = time.time()
    print(f"Training 40-day model from tushare.db (RANDOM 80/20 split, lr=0.03)")
    print("=" * 60)

    # Load GTJA
    print("Loading GTJA...")
    with gzip.open(GTJA_PKL, 'rb') as f:
        gtja = pickle.load(f)
    gtja_lookups = {gn: build_gtja_lookup(gtja, gn) for gn in GTJA_4}
    print(f"  GTJA signals: {[gn for gn in GTJA_4 if gn in gtja]}")

    conn = duckdb.connect(str(DB), read_only=True)

    # Build lookups
    vd = build_valuation_lookup(conn)
    print(f"  Valuation entries: {len(vd):,}")
    af = build_adj_factor_lookup(conn)
    print(f"  Adj factor entries: {len(af):,}")

    # Get stock codes with sufficient data (from 2018 onwards)
    stock_codes = [r[0] for r in conn.execute("""
        SELECT DISTINCT ts_code FROM daily
        WHERE trade_date >= '20180101'
        ORDER BY ts_code
    """).fetchall()]
    print(f"Stocks (2020+): {len(stock_codes)}")

    # === Build panel ===
    X_list, y_list, date_list = [], [], []
    min_rows = FEAT_WIN + FWD_DAYS + 10

    for ci, code in enumerate(stock_codes):
        # Fetch daily data with adj_factor for forward adjustment
        rows = conn.execute(f"""
            SELECT d.trade_date, d.close, COALESCE(d.pct_chg, 0), d.vol,
                   af.adj_factor
            FROM daily d
            LEFT JOIN adj_factor af ON d.ts_code = af.ts_code AND d.trade_date = af.trade_date
            WHERE d.ts_code = '{code}'
            AND d.trade_date >= '20180101'
            ORDER BY d.trade_date
        """).fetchall()

        if len(rows) < min_rows:
            continue

        c_arr = [float(r[1]) for r in rows]
        r_arr = [float(r[2]) / 100 for r in rows]  # pct_chg -> decimal
        a_arr = [float(r[3]) if r[3] else 0 for r in rows]
        dates = [str(r[0]) for r in rows]
        adj_factors = [float(r[4]) if r[4] else 1.0 for r in rows]

        for i in range(FEAT_WIN, len(rows) - FWD_DAYS):
            dt = dates[i]
            v = vd.get((code, dt), {})

            # Compute features
            feat = compute_features(
                c_arr[i - FEAT_WIN:i + 1],
                a_arr[i - FEAT_WIN:i + 1],
                r_arr[i - FEAT_WIN:i + 1],
                v
            )

            # Forward-adjusted close (using adj_factor ratio)
            target_idx = i + FWD_DAYS
            if target_idx < len(rows):
                # Forward-adjusted: close_today * (adj_today / adj_target)
                adj_today = adj_factors[i]
                adj_target = adj_factors[target_idx]
                if adj_today > 0 and adj_target > 0:
                    fwd_close = c_arr[target_idx] * (adj_today / adj_target)
                else:
                    fwd_close = c_arr[target_idx]
                ret = (fwd_close / c_arr[i] - 1) * 100  # percentage
            else:
                continue

            # GTJA features
            gtja_v = [get_gtja_value_fast(code, dt, gtja_lookups[gn]) for gn in GTJA_4]
            feat_full = np.append(feat, np.array(gtja_v, dtype=np.float32))

            X_list.append(feat_full)
            y_list.append(ret)
            date_list.append(dt)

        if (ci + 1) % 200 == 0:
            print(f"  {ci+1}/{len(stock_codes)} stocks, {len(X_list):,} samples [{time.time()-t0:.0f}s]")

    conn.close()

    # === Prepare data ===
    X_raw = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.float32)
    print(f"\nTotal samples: {len(X_raw):,}")
    print(f"Label stats: mean={np.mean(y):+.2f}% std={np.std(y):.2f}%")
    print(f"Label range: [{np.min(y):+.2f}%, {np.max(y):+.2f}%]")

    # Random 80/20 split
    np.random.seed(42)
    n = len(X_raw)
    idx = np.random.permutation(n)
    n_train = int(n * 0.8)
    X_train_raw, y_train = X_raw[idx[:n_train]], y[idx[:n_train]]
    X_val_raw, y_val = X_raw[idx[n_train:]], y[idx[n_train:]]
    print(f"\nTrain: {len(X_train_raw):,} (80%)")
    print(f"Val:   {len(X_val_raw):,} (20%)")

    # Normalization from train only
    print("\nComputing normalization stats (train only)...")
    new_stats = {}
    for j in range(23):  # Only normalize non-GTJA features
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
    print(f"\nTraining LightGBM (lr=0.03, early_stopping=20, max 500 rounds)...")
    dtrain = lgb.Dataset(X_train, y_train)
    dval = lgb.Dataset(X_val, y_val, reference=dtrain)

    params = {
        'objective': 'regression',
        'metric': 'l2',
        'num_leaves': 63,
        'learning_rate': 0.03,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'min_data_in_leaf': 100,
        'verbose': 1,
        'num_threads': -1,  # Use all cores
        'max_depth': 8,
        'device': 'cpu',  # Change to 'gpu' if available
        'first_metric_only': True,
    }

    model = lgb.train(params, dtrain, num_boost_round=500,
                      valid_sets=[dtrain, dval], valid_names=['train', 'val'],
                      callbacks=[lgb.early_stopping(20), lgb.log_evaluation(50)])

    best_iter = model.best_iteration
    pred_train = model.predict(X_train, num_iteration=best_iter)
    pred_val = model.predict(X_val, num_iteration=best_iter)
    ic_train = stats.spearmanr(pred_train, y_train)[0]
    ic_val = stats.spearmanr(pred_val, y_val)[0]

    # === Results ===
    print(f"\n{'='*60}")
    print(f"40-Day Model Results (tushare.db)")
    print(f"{'='*60}")
    print(f"Trees: {model.num_trees()}")
    print(f"Best: {best_iter}")
    print(f"Train IC: {ic_train:.4f}")
    print(f"Val IC:   {ic_val:.4f}")

    # Decile analysis
    val_arr = np.array(list(zip(pred_val, y_val)))
    val_arr = val_arr[val_arr[:, 0].argsort()]
    d10 = len(val_arr) // 10
    for d in range(10):
        s, e = d * d10, (d + 1) * d10 if d < 9 else len(val_arr)
        print(f"  D{d+1}: {np.mean(val_arr[s:e, 1]):+.2f}%")
    spread = np.mean(val_arr[-d10:, 1]) - np.mean(val_arr[:d10, 1])
    print(f"  Spread: {spread:+.1f}%")

    # Feature importance
    imp = model.feature_importance(importance_type='gain')
    top10 = np.argsort(imp)[-10:][::-1]
    total_imp = sum(imp)
    print("\nTop 10 features (gain):")
    for j in top10:
        nm = FEAT_NAMES[j] if j < 23 else f'gtja_{GTJA_4[j-23]}'
        print(f"  {nm:12s}: {imp[j]/total_imp*100:5.1f}%")

    model.save_model(str(OUT_MODEL), num_iteration=best_iter)
    print(f"\nSaved: {OUT_MODEL} ({best_iter} trees, val IC={ic_val:.4f})")
    print(f"Time: {time.time()-t0:.0f}s")


if __name__ == '__main__':
    main()
