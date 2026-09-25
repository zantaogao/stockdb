"""LightGBM 20d 回归训练 — tushare数据源
- 时间切分 (train < 2025-01-01, val >= 2025-01-01)
- 30基础特征 + 2GTJA = 32维
- 前复权使用 adj_factor 表
- 指数数据从 stock.db 补充
"""
import os, json, time, sys
import numpy as np
import lightgbm as lgb
from pathlib import Path
from scipy import stats

sys.stdout.reconfigure(line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent))
from feat_tushare import (
    get_tushare_db, load_index_data, get_board_index, apply_forward_adjust,
    compute_features, load_gtja, get_gtja_value,
    compute_norm_stats, standardize,
    FEAT_WIN, BASE_FEAT_NAMES, N_BASE, GTJA_CODES,
)

# ── 配置 ──
FWD_DAYS = 20

# 时间切分点
_SPLIT_DATE = '20250101'
for i, a in enumerate(sys.argv):
    if a == '--split-date' and i + 1 < len(sys.argv):
        _SPLIT_DATE = sys.argv[i + 1].replace('-', '')
SPLIT_DATE = _SPLIT_DATE

_OUT_SUFFIX = ''
for i, a in enumerate(sys.argv):
    if a == '--suffix' and i + 1 < len(sys.argv):
        _OUT_SUFFIX = f'_{sys.argv[i+1]}'

OUT_DIR = Path(__file__).parent
OUT_MODEL = OUT_DIR / f'lgb_reg_20d_tushare{_OUT_SUFFIX}.txt'
OUT_STATS = OUT_DIR / f'v6_norm_stats_20d_tushare{_OUT_SUFFIX}.json'
OUT_RESULTS = OUT_DIR / f'train_20d_tushare_results{_OUT_SUFFIX}.json'

# ═══════════════════ 主流程 ═══════════════════

def main():
    t0 = time.time()
    print("=" * 60)
    print(f"20d Regression — tushare data (time split: <{SPLIT_DATE})")
    print(f"  Features: {N_BASE} base + {len(GTJA_CODES)} GTJA = {N_BASE + len(GTJA_CODES)}")
    print(f"  Params: lr=0.04, leaves=31, depth=6, 120 rounds, ES=30")
    print("=" * 60)

    # ── 加载数据 ──
    print("\nLoading index data from stock.db...")
    idx_data = load_index_data()
    print(f"  Index codes loaded: {len(idx_data)}")

    print("Loading GTJA...")
    gtja_lookups = load_gtja(GTJA_CODES)
    print(f"  GTJA lookups: {len(gtja_lookups)}")

    con = get_tushare_db()

    stock_codes = [r[0] for r in con.execute(
        "SELECT DISTINCT stock_code FROM stock_daily WHERE date >= '2015-01-01' ORDER BY stock_code"
    ).fetchall()]
    print(f"\nStocks: {len(stock_codes)}")

    # ── 数据构建 ──
    X_raw, y, date_list = [], [], []
    sample_count = 0

    for si, ts_code in enumerate(stock_codes):
        code = ts_code.split('.')[0]

        rows = con.execute(f"""
            SELECT date, close, high, low, COALESCE(change_pct,0), volume
            FROM stock_daily WHERE stock_code='{code}'
            AND date >= '2015-01-01'
            ORDER BY date
        """).fetchall()

        n = len(rows)
        if n < FEAT_WIN + FWD_DAYS + 1:
            continue

        dates = [str(r[0]) for r in rows]
        closes = [float(r[1]) for r in rows]
        highs = [float(r[2]) for r in rows]
        lows = [float(r[3]) for r in rows]
        pcts = [float(r[4]) / 100.0 for r in rows]
        volumes = [float(r[5]) for r in rows]

        # 复权因子
        adj_rows = con.execute(f"""
            SELECT trade_date, adj_factor
            FROM adj_factor WHERE stock_code='{code}'
            ORDER BY trade_date
        """).fetchall()

        closes, highs, lows = apply_forward_adjust(
            closes, highs, lows, adj_rows, dates
        )
        closes = np.array(closes, dtype=np.float64)

        # 估值
        val_rows = con.execute(f"""
            SELECT date, COALESCE(pe_ttm,0), COALESCE(pb,0), COALESCE(total_mv,0)
            FROM stock_valuation WHERE stock_code='{code}'
            ORDER BY date
        """).fetchall()
        val_map = {}
        for dt, pe, pb, mv in val_rows:
            ds = str(dt)[:10]
            v = {}
            if float(pe) > 0: v['ep'] = 1.0 / float(pe)
            if float(pb) > 0: v['bp'] = 1.0 / float(pb)
            if float(mv) > 0: v['ln_cap'] = np.log(float(mv))
            val_map[ds] = v

        # 指数
        board_idx = get_board_index(ts_code)
        idx_info = idx_data.get(board_idx)
        idx_dates = idx_info['dates'] if idx_info else None
        idx_dict = idx_info['dict'] if idx_info else None

        for i in range(FEAT_WIN, n - FWD_DAYS):
            if closes[i] <= 0:
                continue
            dt = dates[i]
            if dt >= '20260618':
                continue
            if closes[i] < 2:
                continue

            v_entry = val_map.get(dt, {})

            # 指数位置 (bisect)
            idx_c = None
            if idx_dates is not None and dt in idx_dict:
                import bisect
                ip = bisect.bisect_left(idx_dates, dt)
                if ip < len(idx_dates) and idx_dates[ip] == dt and ip >= 20:
                    idx_c = [idx_dict[idx_dates[j]] for j in range(ip + 1)]

            feat = compute_features(
                closes[:i+1], np.array(highs[:i+1], dtype=np.float64),
                np.array(lows[:i+1], dtype=np.float64),
                np.array(volumes[:i+1], dtype=np.float64),
                np.array(pcts[:i+1], dtype=np.float64),
                idx_c, v_entry
            )

            # GTJA
            gtja_vals = []
            for gn in GTJA_CODES:
                lookup = gtja_lookups.get(gn)
                gv = get_gtja_value(code, dt, lookup) if lookup else 0.0
                gtja_vals.append(gv)
            feat = np.append(feat, np.array(gtja_vals, dtype=np.float32))

            label = closes[i + FWD_DAYS] / closes[i] - 1
            if label > 0.3 or label < -0.3:
                continue

            X_raw.append(feat)
            y.append(label * 100.0)
            date_list.append(dt)
            sample_count += 1

        if (si + 1) % 500 == 0:
            print(f"  [{si+1}/{len(stock_codes)}] {sample_count:,} samples [{time.time()-t0:.0f}s]", flush=True)

    con.close()

    print(f"\nTotal samples: {len(X_raw):,}")
    X_raw = np.array(X_raw, dtype=np.float32)
    y = np.array(y, dtype=np.float64)
    print(f"Label stats: mean={np.mean(y):+.2f}% std={np.std(y):.2f}%")
    print(f"Label > 0: {np.mean(y > 0) * 100:.0f}%")

    # ── 时间切分 ──
    dates_arr = np.array(date_list)
    train_mask = dates_arr < SPLIT_DATE
    val_mask = dates_arr >= SPLIT_DATE
    X_train_raw, y_train = X_raw[train_mask], y[train_mask]
    X_val_raw, y_val = X_raw[val_mask], y[val_mask]
    print(f"\nTrain (before {SPLIT_DATE}): {train_mask.sum():,} ({train_mask.mean()*100:.0f}%)")
    print(f"Val   (on/after {SPLIT_DATE}): {val_mask.sum():,} ({val_mask.mean()*100:.0f}%)")

    # ── 标准化 ──
    print("\nComputing normalization stats (train only)...")
    stats_dict = compute_norm_stats(X_train_raw)
    X_train = standardize(X_train_raw, stats_dict)
    X_val = standardize(X_val_raw, stats_dict)

    with open(str(OUT_STATS), 'w') as f:
        json.dump(stats_dict, f, indent=2)
    print(f"  Stats saved: {OUT_STATS}")

    # ── 训练 ──
    print("\nTraining LightGBM...")
    params = {
        'objective': 'regression', 'metric': 'l2',
        'num_leaves': 31, 'learning_rate': 0.012,
        'max_depth': 6,
        'feature_fraction': 0.7,
        'bagging_fraction': 0.7, 'bagging_freq': 5,
        'min_data_in_leaf': 150,
        'reg_alpha': 2.5, 'reg_lambda': 2.5,
        'num_threads': 14,
        'device': 'cpu',
        'verbosity': -1,
    }

    dtrain = lgb.Dataset(X_train, y_train)
    dval = lgb.Dataset(X_val, y_val, reference=dtrain)

    model = lgb.train(params, dtrain, num_boost_round=250,
                      valid_sets=[dtrain, dval], valid_names=['train', 'val'],
                      callbacks=[lgb.early_stopping(60), lgb.log_evaluation(25)])

    best_iter = model.best_iteration
    model.save_model(str(OUT_MODEL), num_iteration=best_iter)

    # ── 评估 ──
    pred_val = model.predict(X_val, num_iteration=best_iter)
    pred_train = model.predict(X_train, num_iteration=best_iter)

    ic_train = stats.spearmanr(pred_train, y_train)[0]
    ic_val = stats.spearmanr(pred_val, y_val)[0]

    print(f"\n{'='*60}")
    print(f"20d-tushare Model Results")
    print(f"{'='*60}")
    print(f"Best trees: {best_iter}")
    print(f"Total features: {model.num_feature()}")
    print(f"Train IC: {ic_train:.4f}")
    print(f"Val IC:   {ic_val:.4f}")

    val_order = np.argsort(pred_val)
    n_val = len(val_order)
    decile_size = n_val // 10
    print(f"\nDecile returns (val):")
    d1 = d10 = 0
    for d in range(10):
        idx = val_order[d * decile_size: (d+1) * decile_size]
        avg_ret = np.mean(y_val[idx])
        if d == 0: d1 = avg_ret
        if d == 9: d10 = avg_ret
        print(f"  D{d+1}: {avg_ret:+.2f}%")
    spread = d10 - d1
    hit_rate = np.mean(y_val[val_order[-decile_size:]] > 0) * 100
    print(f"  Spread: {spread:+.2f}%")
    print(f"  D10 hit rate: {hit_rate:.0f}%")

    all_feat_names = BASE_FEAT_NAMES + GTJA_CODES
    imp = model.feature_importance(importance_type='gain')
    total_imp = sum(imp)
    pairs = sorted(zip(all_feat_names, imp), key=lambda x: -x[1])
    print(f"\nTop 10 features (gain):")
    gtja_total = 0
    for fn, imp_v in pairs[:10]:
        pct = imp_v / total_imp * 100
        if 'gtja' in fn: gtja_total += pct
        print(f"  {fn:12s}: {pct:5.1f}%")
    print(f"  GTJA total: {gtja_total:.1f}%")

    results = {
        'ic_val': round(float(ic_val), 4),
        'ic_train': round(float(ic_train), 4),
        'spread_pct': round(float(spread), 2),
        'hit_rate': round(float(hit_rate), 1),
        'best_trees': best_iter,
        'features': len(all_feat_names),
        'train_samples': len(X_train),
        'val_samples': len(X_val),
        'split_date': SPLIT_DATE,
        'time_sec': round(time.time() - t0),
    }
    with open(str(OUT_RESULTS), 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nSaved: {OUT_MODEL} ({best_iter} trees, val IC={ic_val:.4f})")
    print(f"Saved: {OUT_STATS}")
    print(f"Saved: {OUT_RESULTS}")
    print(f"Time: {time.time()-t0:.0f}s")

if __name__ == '__main__':
    main()
