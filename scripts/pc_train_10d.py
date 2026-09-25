"""LightGBM 10日回归训练 — 修正版
修正：
  1. 时间切分（训练<2025-01-01，验证>=2025-01-01）
  2. 标准化统计量从train数据计算
  3. 早停截断

26特征（23基础+3超额收益）+ 4GTJA = 30维
"""
import os, json, gzip, pickle, time, sys
import numpy as np
import lightgbm as lgb
import duckdb
from pathlib import Path
from scipy import stats

BASE = Path.home() / '.hermes' / 'stockdb'
DB = BASE / 'stock.db'
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'
OUT_MODEL = BASE / 'models' / 'lgb_reg_10d.txt'
OUT_STATS = BASE / 'models' / 'v10_norm_stats.json'
OUT_RESULTS = BASE / 'backtest_results' / 'train_10d_results.json'

sys.stdout.reconfigure(line_buffering=True)

FEAT_WIN = 120
FWD_DAYS = 10
SPLIT_DATE = '2025-01-01'
GTJA_4 = ['gtja_006', 'gtja_083', 'gtja_177', 'gtja_184']
FEAT_NAMES = [
    'chg5','chg10','chg20','chg60','chg120',
    'd5','d10','d20','d60','d120',
    'bull1','bull2','rr','std20','vr','pos',
    'nh','vpc','c1d','c3d','ep','bp','ln_cap',
    'ex5','ex10','ex20',
]

def compute_features(c_arr, a_arr, r_arr, idx_c, v):
    """26个特征 + 实际估值数据"""
    c = np.array(c_arr, dtype=np.float64); lc = c[-1]
    chg5=lc/c[-5]-1; chg10=lc/c[-10]-1; chg20=lc/c[-20]-1
    chg60=lc/c[-60]-1; chg120=lc/c[0]-1
    ma5=np.mean(c[-5:]); ma10=np.mean(c[-10:]); ma20=np.mean(c[-20:]); ma60=np.mean(c[-60:])
    d5=lc/ma5-1; d10=lc/ma10-1; d20=lc/ma20-1; d60=lc/ma60-1; d120=lc/np.mean(c)-1
    b1=1 if ma5>ma10>ma20 else 0; b2=1 if ma20>ma60 else 0
    rn=np.max(c[-20:])-np.min(c[-20:])
    rr=rn/np.min(c[-20:])*100 if np.min(c[-20:])>0 else 0
    std20=np.std(c[-20:])/np.mean(c[-20:])*100
    vols=np.array(a_arr[-20:], dtype=np.float64)
    vr=vols[-1]/np.mean(vols) if np.mean(vols)>0 else 1
    rl,rh=np.min(c[-20:]),np.max(c[-20:])
    pos=(lc-rl)/(rh-rl)*100 if rh!=rl else 50
    nh=1 if lc>rh*0.97 else 0; vpc=1 if chg5>0 and vr>1.2 else 0
    c1d=r_arr[-1] if len(r_arr)>0 else 0
    c3d=lc/c[-3]-1 if len(c)>=3 else 0
    ep=v.get('ep',0.5); bp=v.get('bp',0.5); ln_cap=v.get('ln_cap',22.0)
    if idx_c is not None and len(idx_c)>=20:
        ex5=chg5-(idx_c[-1]/idx_c[-5]-1); ex10=chg10-(idx_c[-1]/idx_c[-10]-1); ex20=chg20-(idx_c[-1]/idx_c[-20]-1)
    else: ex5=ex10=ex20=0.0
    return np.array([chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,
        b1,b2,rr,std20,vr,pos,nh,vpc,c1d,c3d,ep,bp,ln_cap,ex5,ex10,ex20], dtype=np.float32)

def build_gtja_lookup(gtja_dict, gn):
    if gn not in gtja_dict: return None, None
    df = gtja_dict[gn]; dates = sorted(df.index)
    return dates, df

import bisect
def get_gtja_value_fast(code, date_str, gtja_lookup):
    dates, df = gtja_lookup
    if dates is None: return 0.0
    if isinstance(dates[0], str):
        idx = bisect.bisect_right(dates, date_str) - 1
        if idx >= 0:
            d = dates[idx]
            if code in df.columns:
                val = df.loc[d, code]
                return float(val) if not np.isnan(val) else 0.0
    return 0.0


def main():
    t0 = time.time()
    print("=" * 60, flush=True)
    print(f"Training 10d model (time-split: train<{SPLIT_DATE}, val>={SPLIT_DATE})", flush=True)
    print("=" * 60, flush=True)

    # Load GTJA
    print("\nLoading GTJA...", flush=True)
    with gzip.open(GTJA_PKL, 'rb') as f: gtja = pickle.load(f)
    gtja_lookups = {gn: build_gtja_lookup(gtja, gn) for gn in GTJA_4}

    conn = duckdb.connect(str(DB), read_only=True)

    # 预加载估值
    print("Loading valuation data...", flush=True)
    vd = {}
    val_rows = conn.execute("""
        SELECT stock_code, date, pe_ttm, pb, total_mv
        FROM stock_valuation ORDER BY stock_code, date
    """).fetchall()
    for code, dt, pe, pb, mv in val_rows:
        ds = str(dt)[:10]; v = {}
        if pe and pe > 0: v['ep'] = 1.0 / float(pe)
        if pb and pb > 0: v['bp'] = 1.0 / float(pb)
        if mv and mv > 0: v['ln_cap'] = np.log(float(mv))
        if v: vd[(code, ds)] = v
    print(f"  Valuation entries: {len(vd)}")

    stock_codes = [r[0] for r in conn.execute(
        "SELECT DISTINCT stock_code FROM stock_daily ORDER BY stock_code").fetchall()]
    print(f"Stocks: {len(stock_codes)}", flush=True)

    X_list, y_list, date_list = [], [], []
    total_stocks = len(stock_codes)

    for ci, code in enumerate(stock_codes):
        rows = conn.execute(f"""
            SELECT date, close, COALESCE(change_pct,0), volume
            FROM stock_daily WHERE stock_code='{code}'
            AND date >= '2019-06-01' ORDER BY date
        """).fetchall()
        if len(rows) < FEAT_WIN + FWD_DAYS + 10: continue

        c_arr = [float(r[1]) for r in rows]
        r_arr = [float(r[2])/100.0 for r in rows]
        a_arr = [float(r[3]) if r[3] else 0 for r in rows]
        dates = [str(r[0])[:10] for r in rows]

        first_date = dates[0]
        idx_rows = conn.execute(f"""
            SELECT date, close FROM index_daily
            WHERE index_code='000001' AND date >= '{first_date}' ORDER BY date
        """).fetchall()
        idx_map = {str(r[0])[:10]: float(r[1]) for r in idx_rows}
        idx_c_arr = []
        for d in dates:
            val = idx_map.get(d)
            if val is not None: idx_c_arr.append(val)
            elif idx_c_arr: idx_c_arr.append(idx_c_arr[-1])
            else: idx_c_arr.append(0)

        for i in range(FEAT_WIN, len(rows) - FWD_DAYS):
            dt = dates[i]
            if c_arr[i] <= 0: continue
            idx_win = np.array(idx_c_arr[i-FEAT_WIN:i+1]) if len(idx_c_arr) >= i+1 else None
            v = vd.get((code, dt), {})
            feat = compute_features(
                c_arr[i-FEAT_WIN:i+1], a_arr[i-FEAT_WIN:i+1],
                r_arr[i-FEAT_WIN:i+1], idx_win, v)
            gtja_v = [get_gtja_value_fast(code, dt, gtja_lookups[gn]) for gn in GTJA_4]
            X_list.append(np.append(feat, np.array(gtja_v, dtype=np.float32)))
            fc = c_arr[i+FWD_DAYS]
            y_list.append(fc / c_arr[i] - 1)
            date_list.append(dt)

        if (ci+1) % 500 == 0:
            print(f"  {ci+1}/{total_stocks} stocks, {len(X_list)} samples [{time.time()-t0:.0f}s]", flush=True)

    conn.close()

    X_raw = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.float32)
    dates_arr = np.array(date_list)
    print(f"\nTotal samples: {len(X_raw):,}", flush=True)
    print(f"Label stats: mean={np.mean(y)*100:+.3f}% std={np.std(y)*100:.3f}%", flush=True)

    # ── 时间切分 ──
    train_mask = dates_arr < SPLIT_DATE
    val_mask = dates_arr >= SPLIT_DATE
    X_train_raw, y_train = X_raw[train_mask], y[train_mask]
    X_val_raw, y_val = X_raw[val_mask], y[val_mask]
    print(f"Train (before {SPLIT_DATE}): {len(X_train_raw):,} ({train_mask.mean()*100:.0f}%)", flush=True)
    print(f"Val   (on/after {SPLIT_DATE}): {len(X_val_raw):,} ({val_mask.mean()*100:.0f}%)", flush=True)

    # 标准化统计量（仅从train数据）
    print("Computing normalization stats (train only)...", flush=True)
    new_stats = {}
    for j in range(30):
        vals = X_train_raw[:, j]
        valid = vals[~np.isnan(vals)]
        if len(valid) > 0:
            new_stats[f'feat_{j}'] = {
                'mean': float(np.mean(valid)), 'std': float(np.std(valid)),
                'low': float(np.percentile(valid, 1)), 'high': float(np.percentile(valid, 99))
            }

    def normalize(X, stats):
        Xn = X.copy()
        for j in range(30):
            key = f'feat_{j}'
            if key in stats and stats[key]['std'] > 0:
                s = stats[key]
                Xn[:, j] = np.clip(Xn[:, j], s['low'], s['high'])
                Xn[:, j] = (Xn[:, j] - s['mean']) / s['std']
        return np.nan_to_num(Xn, nan=0.0)

    X_train_n = normalize(X_train_raw, new_stats)
    X_val_n = normalize(X_val_raw, new_stats)

    with open(OUT_STATS, 'w') as f:
        json.dump(new_stats, f)
    print(f"Stats saved: {OUT_STATS}", flush=True)

    # 训练（早停）
    print(f"\nTraining LightGBM (early stopping @ val l2)...", flush=True)
    dtrain = lgb.Dataset(X_train_n, y_train)
    dval = lgb.Dataset(X_val_n, y_val, reference=dtrain)

    params = {
        'objective': 'regression', 'metric': 'l2',
        'num_leaves': 31, 'learning_rate': 0.01,
        'feature_fraction': 0.7, 'bagging_fraction': 0.7,
        'bagging_freq': 5, 'min_data_in_leaf': 500,
        'reg_alpha': 1.0, 'reg_lambda': 1.0,
        'verbose': 1, 'num_threads': 6, 'max_depth': 6,
        'device': 'cpu',
    }

    model = lgb.train(params, dtrain, num_boost_round=1000,
                      valid_sets=[dtrain, dval], valid_names=['train', 'val'],
                      callbacks=[lgb.early_stopping(30), lgb.log_evaluation(50)])

    # Evaluate on val set
    best_iter = model.best_iteration
    pred_val = model.predict(X_val_n, num_iteration=best_iter)
    ic_val = stats.spearmanr(pred_val, y_val)[0]

    print(f"\n{'='*60}", flush=True)
    print(f"Results", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"Best trees: {best_iter}", flush=True)
    print(f"Features: {model.num_feature()}", flush=True)
    print(f"Val IC: {ic_val:.4f}", flush=True)

    # Decile on val
    full_arr = np.array(list(zip(pred_val, y_val)))
    full_arr = full_arr[full_arr[:, 0].argsort()]
    d10 = len(full_arr) // 10
    print("Decile returns (val):", flush=True)
    for d in range(10):
        start, end = d*d10, (d+1)*d10 if d<9 else len(full_arr)
        avg_ret = np.mean(full_arr[start:end, 1])*100
        print(f"  D{d+1}: {avg_ret:+.2f}%", flush=True)
    spread = (np.mean(full_arr[-d10:, 1]) - np.mean(full_arr[:d10, 1])) * 100
    print(f"  Spread: {spread:+.2f}%", flush=True)

    # Feature importance
    imp = model.feature_importance(importance_type='gain')
    top10 = np.argsort(imp)[-10:][::-1]
    print("Top 10 features (gain):", flush=True)
    for j in top10:
        name = FEAT_NAMES[j] if j < 26 else f'gtja_{j-26}'
        print(f"  feat_{j} ({name}): {imp[j]:.0f}", flush=True)

    # Save best model
    model.save_model(str(OUT_MODEL), num_iteration=best_iter)
    result = {
        'ic_val': round(float(ic_val), 4),
        'spread_pct': round(float(spread), 2),
        'best_trees': best_iter,
        'total_trees': model.num_trees(),
        'features': model.num_feature(),
        'train_samples': len(X_train_raw),
        'val_samples': len(X_val_raw),
        'time_sec': int(time.time()-t0),
    }
    with open(OUT_RESULTS, 'w') as f: json.dump(result, f, indent=2)
    print(f"\nModel saved: {OUT_MODEL} ({best_iter} trees, val IC={ic_val:.4f})", flush=True)
    print(f"Results saved: {OUT_RESULTS}", flush=True)
    print(f"Time: {result['time_sec']}s", flush=True)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
