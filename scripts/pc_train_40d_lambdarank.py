"""LightGBM LambdaRank — 40日收益率排名模型
时间切分：train < 2025-01-01, val >= 2025-01-01
每个交易日为一个query group，优化NDCG（排序质量）

标签：按每个交易日内的40日收益率做5分位 → relevance 0-4
特征：23基础 + 4GTJA = 27维（同旧40d回归模型）
"""
import os, json, gzip, pickle, time, sys
import numpy as np
import lightgbm as lgb
import duckdb
from pathlib import Path
from scipy import stats

BASE = Path('C:/Users/pumma/factor_lib')
DB = BASE / 'stock.db'
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'
OUT_MODEL = BASE / 'lgb_reg_40d_lambda.txt'
OUT_STATS = BASE / 'v6_norm_stats_40d_lambda.json'

sys.stdout.reconfigure(line_buffering=True)

FEAT_WIN = 120
FWD_DAYS = 40
SPLIT_DATE = '2025-01-01'
N_LEVELS = 5  # 5-level relevance
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
    ma5 = np.mean(c[-5:]); ma10 = np.mean(c[-10:])
    ma20 = np.mean(c[-20:]); ma60 = np.mean(c[-60:])
    d5 = lc/ma5-1; d10 = lc/ma10-1; d20 = lc/ma20-1
    d60 = lc/ma60-1; d120 = lc/np.mean(c)-1
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
    ep = v.get('ep', 0.5); bp = v.get('bp', 0.5); ln_cap = v.get('ln_cap', 22.0)
    return np.array([chg5, chg10, chg20, chg60, chg120,
                     d5, d10, d20, d60, d120,
                     b1, b2, rr, std20, vr, pos,
                     nh, vpc, c1d, c3d, ep, bp, ln_cap], dtype=np.float32)


def build_gtja_lookup(gtja_dict, gn):
    if gn not in gtja_dict: return None, None, None
    df = gtja_dict[gn]
    dates = [str(d)[:10] for d in sorted(df.index)]
    return dates, df, None


def get_gtja_value_fast(code, date_str, gtja_lookup):
    import bisect
    dates, df, _ = gtja_lookup
    if dates is None: return 0.0
    idx = bisect.bisect_right(dates, date_str[:10]) - 1
    if idx >= 0:
        d = dates[idx]
        if code in df.columns:
            val = df.loc[d, code]
            return float(val) if not np.isnan(val) else 0.0
    return 0.0


def discretize_labels(y_group):
    """将一组连续收益率转为0~N_LEVELS-1的离散排序标签（基于五分位）"""
    n = len(y_group)
    if n < N_LEVELS:
        # 样本太少，用线性映射
        sorted_idx = np.argsort(y_group)
        levels = np.zeros(n, dtype=np.int32)
        for i, idx in enumerate(sorted_idx):
            levels[idx] = int(i * N_LEVELS / n)
        return levels, y_group
    # 五分位
    bins = np.percentile(y_group, [20, 40, 60, 80])
    levels = np.zeros(n, dtype=np.int32)
    for i in range(1, N_LEVELS):
        levels[y_group > bins[i-1]] = i
    return levels, y_group


def main():
    t0 = time.time()
    print(f"Training LambdaRank 40d (time-split: train<{SPLIT_DATE})")
    print("=" * 60)

    # Load GTJA
    print("Loading GTJA...")
    with gzip.open(GTJA_PKL, 'rb') as f:
        gtja = pickle.load(f)
    gtja_lookups = {gn: build_gtja_lookup(gtja, gn) for gn in GTJA_4}

    conn = duckdb.connect(str(DB), read_only=True)

    # 预加载估值
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

    stock_codes = [r[0] for r in conn.execute(
        "SELECT DISTINCT stock_code FROM stock_daily WHERE date >= '2020-01-01' ORDER BY stock_code").fetchall()]
    print(f"Stocks: {len(stock_codes)}")

    # Build data: date→[features, labels]
    date_data = {}  # {date_str: {'X': [], 'y': []}}
    for ci, code in enumerate(stock_codes):
        rows = conn.execute(f"""
            SELECT date, close, COALESCE(change_pct,0), volume
            FROM stock_daily WHERE stock_code='{code}'
            AND date >= '2020-01-01' ORDER BY date
        """).fetchall()
        if len(rows) < FEAT_WIN + FWD_DAYS + 10: continue

        c_arr = [float(r[1]) for r in rows]
        r_arr = [float(r[2]) / 100.0 for r in rows]
        a_arr = [float(r[3]) if r[3] else 0 for r in rows]
        dates = [str(r[0])[:10] for r in rows]

        for i in range(FEAT_WIN, len(rows) - FWD_DAYS):
            dt = dates[i]
            v = vd.get((code, dt), {})
            feat = compute_features(
                c_arr[i-FEAT_WIN:i+1], a_arr[i-FEAT_WIN:i+1], r_arr[i-FEAT_WIN:i+1], v)
            gtja_v = [get_gtja_value_fast(code, dt, gtja_lookups[gn]) for gn in GTJA_4]
            feat_full = np.append(feat, np.array(gtja_v, dtype=np.float32))
            ret = (c_arr[i+FWD_DAYS] / c_arr[i] - 1) * 100
            date_data.setdefault(dt, {'X': [], 'y': []})
            date_data[dt]['X'].append(feat_full)
            date_data[dt]['y'].append(ret)

        if (ci + 1) % 100 == 0:
            msg = f'  {ci+1}/{len(stock_codes)} stocks, {sum(len(v["y"]) for v in date_data.values())} samples [{time.time()-t0:.0f}s]'
            print(msg, flush=True)

    conn.close()
    print(f"Total dates with data: {len(date_data)}", flush=True)

    # Sort by date, build arrays + group info
    sorted_dates = sorted(date_data.keys())
    all_X, all_y, all_levels, groups = [], [], [], []
    train_groups, val_groups = [], []

    for dt in sorted_dates:
        dd = date_data[dt]
        y_arr = np.array(dd['y'], dtype=np.float32)
        if len(y_arr) < 10: continue  # 太少股票无排名意义

        levels, _ = discretize_labels(y_arr)
        n = len(y_arr)
        is_train = dt < SPLIT_DATE

        for feat in dd['X']:
            all_X.append(feat)
        all_y.extend(y_arr.tolist())
        all_levels.extend(levels.tolist())
        groups.append(n)
        if is_train:
            train_groups.append(n)
        else:
            val_groups.append(n)

    X_raw = np.array(all_X, dtype=np.float32)
    y_cont = np.array(all_y, dtype=np.float32)
    y_label = np.array(all_levels, dtype=np.int32)
    group_arr = np.array(groups, dtype=np.int32)

    print(f"\nTotal samples: {len(X_raw):,}", flush=True)
    print(f"Query groups: {len(groups)}", flush=True)
    print(f"Label distribution: level0={np.mean(y_label==0)*100:.0f}% "
          f"level1={np.mean(y_label==1)*100:.0f}% "
          f"level2={np.mean(y_label==2)*100:.0f}% "
          f"level3={np.mean(y_label==3)*100:.0f}% "
          f"level4={np.mean(y_label==4)*100:.0f}%", flush=True)
    print(f"Label cont: mean={np.mean(y_cont):+.2f}% std={np.std(y_cont):.2f}%", flush=True)

    # ── 时间切分 ──
    n_train = sum(train_groups)
    n_val = sum(val_groups)
    print(f"\nTrain groups: {len(train_groups)}, {n_train:,} samples ({n_train/len(X_raw)*100:.0f}%)", flush=True)
    print(f"Val   groups: {len(val_groups)}, {n_val:,} samples ({n_val/len(X_raw)*100:.0f}%)", flush=True)

    X_train_raw = X_raw[:n_train]
    y_train_cont = y_cont[:n_train]
    y_train_label = y_label[:n_train]
    train_group_arr = np.array(train_groups, dtype=np.int32)

    X_val_raw = X_raw[n_train:]
    y_val_cont = y_cont[n_train:]
    y_val_label = y_label[n_train:]
    val_group_arr = np.array(val_groups, dtype=np.int32)

    # 标准化统计量（仅从train数据，仅前23个基础特征）
    print("Computing normalization stats (train only)...", flush=True)
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
    print(f"Stats saved: {OUT_STATS}", flush=True)

    # ── LambdaRank 训练 ──
    print("\nTraining LambdaRank...", flush=True)
    dtrain = lgb.Dataset(X_train, label=y_train_label, group=train_group_arr)
    dval = lgb.Dataset(X_val, label=y_val_label, group=val_group_arr, reference=dtrain)

    params = {
        'objective': 'lambdarank',
        'metric': 'ndcg',
        'ndcg_eval_at': [5, 10],
        'label_gain': list(range(N_LEVELS)),  # [0, 1, 2, 3, 4]
        'num_leaves': 63,
        'learning_rate': 0.05,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'min_data_in_leaf': 50,
        'min_sum_hessian_in_leaf': 1e-3,
        'reg_alpha': 1.0,
        'reg_lambda': 1.0,
        'verbose': 1,
        'num_threads': 6,
        'max_depth': 8,
        'device': 'gpu',
        'first_metric_only': True,
    }

    model = lgb.train(params, dtrain, num_boost_round=1000,
                      valid_sets=[dtrain, dval], valid_names=['train', 'val'],
                      callbacks=[lgb.early_stopping(30), lgb.log_evaluation(50)])

    best_iter = model.best_iteration

    # ── 评估 ──
    # 1) NDCG
    print(f"\n{'='*60}")
    print(f"LambdaRank 40d Results (time-split)")
    print(f"{'='*60}")
    print(f"Best trees: {best_iter}")
    print(f"Features: {model.num_feature()}")

    # 2) 连续标签上的秩IC（用原始收益率而非离散标签）
    pred_train = model.predict(X_train, num_iteration=best_iter)
    pred_val = model.predict(X_val, num_iteration=best_iter)

    ic_train = stats.spearmanr(pred_train, y_train_cont)[0]
    ic_val = stats.spearmanr(pred_val, y_val_cont)[0]
    print(f"Train IC (vs continuous y): {ic_train:.4f}")
    print(f"Val   IC (vs continuous y): {ic_val:.4f}")

    # 3) 验证集上的分组收益（用连续标签）
    val_arr = np.array(list(zip(pred_val, y_val_cont)))
    val_arr = val_arr[val_arr[:, 0].argsort()]
    d10 = len(val_arr) // 10
    print(f"\nDecile returns (val, raw scores):")
    for d in range(10):
        start = d * d10
        end = start + d10 if d < 9 else len(val_arr)
        avg_ret = np.mean(val_arr[start:end, 1])
        print(f"  D{d+1}: {avg_ret:+.2f}%")
    spread = np.mean(val_arr[-d10:, 1]) - np.mean(val_arr[:d10, 1])
    hit_rate = np.mean(val_arr[-d10:, 1] > 0) * 100
    print(f"  Spread: {spread:+.1f}%", flush=True)
    print(f"  D10 hit rate: {hit_rate:.0f}%", flush=True)

    # 4) Feature importance
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

    # Save
    model.save_model(str(OUT_MODEL), num_iteration=best_iter)
    print(f"\nSaved: {OUT_MODEL} ({best_iter} trees, val IC={ic_val:.4f})")
    print(f"Time: {time.time()-t0:.0f}s")


if __name__ == '__main__':
    main()
