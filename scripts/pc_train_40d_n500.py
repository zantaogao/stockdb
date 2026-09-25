"""Train LightGBM regression with 40-day forward return label — early stopping
时间切分：train < 2025-01-01, val >= 2025-01-01
Early stopping with patience=50, max 500 trees to prevent overfitting.
"""
import os, json, gzip, pickle, time, sys, numpy as np
import lightgbm as lgb
import duckdb
from pathlib import Path
from scipy import stats

# Force line-buffered output
sys.stdout.reconfigure(line_buffering=True)

BASE = Path('C:/Users/pumma/factor_lib')
DB = BASE / 'stock.db'
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'
OUT_MODEL = BASE / 'lgb_reg_40d.txt'
OUT_STATS = BASE / 'v6_norm_stats_40d.json'

FEAT_WIN = 120
FWD_DAYS = 40
SPLIT_DATE = '2025-01-01'
GTJA_4 = ['gtja_006', 'gtja_083', 'gtja_177', 'gtja_184']
FEAT_NAMES = [
    'chg5','chg10','chg20','chg60','chg120',
    'd5','d10','d20','d60','d120',
    'bull1','bull2','rr','std20','vr','pos',
    'nh','vpc','c1d','c3d','ep','bp','ln_cap',
]

def compute_features(c_arr, a_arr, r_arr, v):
    """23个基础特征 + 真实估值数据"""
    c = np.array(c_arr)
    lc = c[-1]
    chg5 = lc/c[-5]-1; chg10 = lc/c[-10]-1; chg20 = lc/c[-20]-1
    chg60 = lc/c[-60]-1; chg120 = lc/c[0]-1
    ma5 = np.mean(c[-5:]); ma10 = np.mean(c[-10:]); ma20 = np.mean(c[-20:]); ma60 = np.mean(c[-60:])
    d5 = lc/ma5-1; d10 = lc/ma10-1; d20 = lc/ma20-1; d60 = lc/ma60-1; d120 = lc/np.mean(c)-1
    b1 = 1 if ma5 > ma10 > ma20 else 0; b2 = 1 if ma20 > ma60 else 0
    rn = np.max(c[-20:]) - np.min(c[-20:])
    rr = rn / np.min(c[-20:]) * 100 if np.min(c[-20:]) > 0 else 0
    std20 = np.std(c[-20:]) / np.mean(c[-20:]) * 100
    vols = np.array(a_arr[-20:])
    vr = vols[-1] / np.mean(vols) if np.mean(vols) > 0 else 1
    rl, rh = np.min(c[-20:]), np.max(c[-20:])
    pos = (lc - rl) / (rh - rl) * 100 if rh != rl else 50
    nh = 1 if lc > rh * 0.97 else 0
    vpc = 1 if chg5 > 0 and vr > 1.2 else 0
    c1d = r_arr[-1] if len(r_arr) > 0 else 0
    c3d = lc / c[-3] - 1 if len(c) >= 3 else 0
    # 真实估值数据（从预加载的vd字典获取）
    ep = v.get('ep', 0.5)
    bp = v.get('bp', 0.5)
    ln_cap = v.get('ln_cap', 22.0)
    return np.array([chg5, chg10, chg20, chg60, chg120,
                     d5, d10, d20, d60, d120,
                     b1, b2, rr, std20, vr, pos,
                     nh, vpc, c1d, c3d, ep, bp, ln_cap], dtype=np.float32)


def build_gtja_lookup(gtja_dict, gn):
    if gn not in gtja_dict: return None, None
    df = gtja_dict[gn]
    dates = [str(d)[:10] for d in sorted(df.index)]
    return dates, df


def get_gtja_value_fast(code, date_str, gtja_lookup):
    import bisect
    dates, df = gtja_lookup
    if dates is None: return 0.0
    idx = bisect.bisect_right(dates, date_str[:10]) - 1
    if idx >= 0:
        d = dates[idx]
        if code in df.columns:
            val = df.loc[d, code]
            return float(val) if not np.isnan(val) else 0.0
    return 0.0


def main():
    t0 = time.time()
    print(f"Training 40-day model (time-split: train<{SPLIT_DATE}, val>={SPLIT_DATE})")
    print("=" * 60)

    # Load GTJA
    print("Loading GTJA...")
    with gzip.open(GTJA_PKL, 'rb') as f:
        gtja = pickle.load(f)
    gtja_lookups = {gn: build_gtja_lookup(gtja, gn) for gn in GTJA_4}
    print(f"GTJA lookups built for {len(gtja_lookups)} factors")

    conn = duckdb.connect(str(DB), read_only=True)

    # 预加载估值数据
    print("Loading valuation data...")
    vd = {}
    val_rows = conn.execute("""
        SELECT stock_code, date, pe_ttm, pb, total_mv
        FROM stock_valuation ORDER BY stock_code, date
    """).fetchall()
    for code, dt, pe, pb, mv in val_rows:
        ds = str(dt)[:10]
        v = {}
        if pe and pe > 0: v['ep'] = 1.0 / float(pe)
        if pb and pb > 0: v['bp'] = 1.0 / float(pb)
        if mv and mv > 0: v['ln_cap'] = np.log(float(mv))
        if v: vd[(code, ds)] = v
    print(f"  Valuation entries: {len(vd)}")

    # All stocks
    stock_codes = [r[0] for r in conn.execute(
        "SELECT DISTINCT stock_code FROM stock_daily WHERE date >= '2020-01-01' ORDER BY stock_code").fetchall()]
    print(f"Stocks: {len(stock_codes)}")

    # Build training data
    X_list, y_list, date_list = [], [], []

    for ci, code in enumerate(stock_codes):
        rows = conn.execute(f"""
            SELECT date, close, COALESCE(change_pct,0), volume
            FROM stock_daily WHERE stock_code='{code}'
            AND date >= '2020-01-01' ORDER BY date
        """).fetchall()

        if len(rows) < FEAT_WIN + FWD_DAYS + 10:
            continue

        c_arr = [float(r[1]) for r in rows]
        r_arr = [float(r[2]) / 100.0 for r in rows]
        a_arr = [float(r[3]) if r[3] else 0 for r in rows]
        dates = [str(r[0])[:10] for r in rows]

        for i in range(FEAT_WIN, len(rows) - FWD_DAYS):
            dt = dates[i]
            v = vd.get((code, dt), {})
            feat = compute_features(
                c_arr[i - FEAT_WIN : i + 1],
                a_arr[i - FEAT_WIN : i + 1],
                r_arr[i - FEAT_WIN : i + 1],
                v,
            )

            # GTJA factors
            gtja_v = [get_gtja_value_fast(code, dt, gtja_lookups[gn]) for gn in GTJA_4]
            feat_full = np.append(feat, np.array(gtja_v, dtype=np.float32))

            # 40-day forward return (%)
            fc = c_arr[i + FWD_DAYS]
            ret = (fc / c_arr[i] - 1) * 100
            X_list.append(feat_full)
            y_list.append(ret)
            date_list.append(dt)

        if (ci + 1) % 100 == 0:
            msg = f'  {ci+1}/{len(stock_codes)} stocks, {len(X_list)} samples'
            print(msg, flush=True)

    conn.close()

    X_raw = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.float32)
    dates_arr = np.array(date_list)

    print(f"\nTotal samples: {len(X_raw):,}")
    print(f"Label stats: mean={np.mean(y):+.2f}% std={np.std(y):.2f}%")
    print(f"Label > 0: {np.mean(y > 0) * 100:.0f}%")

    # ── 时间切分 ──
    train_mask = dates_arr < SPLIT_DATE
    val_mask = dates_arr >= SPLIT_DATE
    X_train_raw, y_train = X_raw[train_mask], y[train_mask]
    X_val_raw, y_val = X_raw[val_mask], y[val_mask]
    print(f"\nTrain (before {SPLIT_DATE}): {len(X_train_raw):,} ({train_mask.mean()*100:.0f}%)")
    print(f"Val   (on/after {SPLIT_DATE}): {len(X_val_raw):,} ({val_mask.mean()*100:.0f}%)")

    # 标准化统计量：仅从train数据计算
    print("\nComputing normalization stats (train only)...")
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

    # 保存标准化统计量
    with open(OUT_STATS, 'w') as f:
        json.dump(new_stats, f)
    print(f"Stats saved: {OUT_STATS}")

    # Sanity check
    for j in range(23):
        v = X_train[:, j]
        std_val = float(np.std(v[~np.isnan(v)]))
        if std_val < 0.001:
            print(f"  [WARN] feat_{j} ({FEAT_NAMES[j]}) near-zero variance: {std_val:.6f}")

    # Train with early stopping (low lr, high patience)
    print(f"\nTraining LightGBM (lr=0.005, patience=100, max 500 rounds)...")
    dtrain = lgb.Dataset(X_train, y_train)
    dval = lgb.Dataset(X_val, y_val, reference=dtrain)

    params = {
        'objective': 'regression', 'metric': 'l2',
        'num_leaves': 31, 'learning_rate': 0.005,
        'feature_fraction': 0.7, 'bagging_fraction': 0.7,
        'bagging_freq': 5, 'min_data_in_leaf': 100,
        'verbose': 1, 'num_threads': 6, 'max_depth': 6,
        'device': 'gpu',
        'first_metric_only': True,
    }

    model = lgb.train(params, dtrain, num_boost_round=500,
                      valid_sets=[dtrain, dval], valid_names=['train', 'val'],
                      callbacks=[lgb.early_stopping(100), lgb.log_evaluation(50)])

    # Evaluate at best iteration
    best_iter = model.best_iteration
    pred_train = model.predict(X_train, num_iteration=best_iter)
    pred_val = model.predict(X_val, num_iteration=best_iter)

    ic_train = stats.spearmanr(pred_train, y_train)[0]
    ic_val = stats.spearmanr(pred_val, y_val)[0]

    print(f"\n{'='*60}")
    print(f"40-Day Model Results (time-split)")
    print(f"{'='*60}")
    print(f"Total trees trained: {model.num_trees()}")
    print(f"Best iteration (val): {best_iter}")
    print(f"Total features: {model.num_feature()}")
    print(f"Train IC: {ic_train:.4f}")
    print(f"Val IC:   {ic_val:.4f}")

    # Decile analysis (on val set)
    val_arr = np.array(list(zip(pred_val, y_val)))
    val_arr = val_arr[val_arr[:, 0].argsort()]
    d10 = len(val_arr) // 10
    print(f"\nDecile returns (val):")
    for d in range(10):
        start = d * d10
        end = start + d10 if d < 9 else len(val_arr)
        avg_ret = np.mean(val_arr[start:end, 1])
        print(f"  D{d+1}: {avg_ret:+.2f}%")
    spread = np.mean(val_arr[-d10:, 1]) - np.mean(val_arr[:d10, 1])
    hit_rate = np.mean(val_arr[-d10:, 1] > 0) * 100
    print(f"  Spread: {spread:+.1f}%")
    print(f"  D10 hit rate: {hit_rate:.0f}%")

    # Feature importance
    imp = model.feature_importance(importance_type='gain')
    top10 = np.argsort(imp)[-10:][::-1]
    total_gain = sum(imp)
    print(f"\nTop 10 features (gain):")
    for j in top10:
        nm = FEAT_NAMES[j] if j < 23 else f'gtja_{j-23}'
        pct = imp[j] / total_gain * 100
        print(f"  feat_{j:2d} ({nm:6s}): {imp[j]:>12,.0f}  ({pct:5.1f}%)")
    gtja_total = sum(imp[23:]) / total_gain * 100 if len(imp) > 23 else 0
    print(f"  GTJA total: {gtja_total:.1f}%")

    # Save all 1000 trees (or best_iter)
    model.save_model(str(OUT_MODEL), num_iteration=best_iter)
    print(f"\nSaved: {OUT_MODEL} ({best_iter} trees, val IC={ic_val:.4f})")
    print(f"Saved: {OUT_STATS}")
    print(f"Time: {time.time()-t0:.0f}s")


if __name__ == '__main__':
    main()
