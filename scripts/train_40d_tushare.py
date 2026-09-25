"""LightGBM 40d 回归训练 — tushare数据源
- 随机80/20拆分（40d噪声大，时间切分会退化到1棵树）
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

# 加载共享模块
sys.path.insert(0, str(Path(__file__).parent))
from feat_tushare import (
    get_tushare_db, load_index_data, get_board_index, apply_forward_adjust,
    compute_features, load_gtja, get_gtja_value,
    compute_norm_stats, standardize,
    FEAT_WIN, BASE_FEAT_NAMES, N_BASE, GTJA_CODES,
)

# ── 配置 ──
FWD_DAYS = 40
SEED = 42

# 输出路径
OUT_DIR = Path(__file__).parent
_OUT_SUFFIX = ''
for i, a in enumerate(sys.argv):
    if a == '--suffix' and i + 1 < len(sys.argv):
        _OUT_SUFFIX = f'_{sys.argv[i+1]}'

OUT_MODEL = OUT_DIR / f'lgb_reg_40d_tushare{_OUT_SUFFIX}.txt'
OUT_STATS = OUT_DIR / f'v6_norm_stats_40d_tushare{_OUT_SUFFIX}.json'
OUT_RESULTS = OUT_DIR / f'train_40d_tushare_results{_OUT_SUFFIX}.json'

# ── 标签 ──
def score_40d(pred):
    """预测值(百分数) -> 评分 0~100"""
    s = (pred + 10) / 50 * 100.0
    return max(0.0, min(100.0, s))

# ═══════════════════ 主流程 ═══════════════════

def main():
    t0 = time.time()
    print("=" * 60)
    print(f"40d Regression — tushare data (random 80/20 split, seed={SEED})")
    print(f"  Features: {N_BASE} base + {len(GTJA_CODES)} GTJA = {N_BASE + len(GTJA_CODES)}")
    print(f"  Params: lr=0.03, leaves=63, depth=8, 500 rounds, ES=20")
    print("=" * 60)

    # ── 加载数据 ──
    print("\nLoading index data from stock.db...")
    idx_data = load_index_data()
    idx_codes_loaded = list(idx_data.keys())
    print(f"  Index codes: {idx_codes_loaded}")

    print("Loading GTJA...")
    gtja_lookups = load_gtja(GTJA_CODES)
    print(f"  GTJA lookups: {len(gtja_lookups)}")

    # ── tushare 连接 ──
    con = get_tushare_db()

    # 获取所有股票代码
    stock_codes = [r[0] for r in con.execute(
        "SELECT DISTINCT stock_code FROM stock_daily WHERE date >= '2015-01-01' ORDER BY stock_code"
    ).fetchall()]
    print(f"\nStocks: {len(stock_codes)}")

    # ── 数据构建 ──
    X_raw, y, date_list = [], [], []
    sample_count = 0

    for si, ts_code in enumerate(stock_codes):
        code = ts_code.split('.')[0]  # 去掉 .SZ/.SH

        # 日线数据
        rows = con.execute(f"""
            SELECT date, close, high, low, COALESCE(change_pct,0), volume
            FROM stock_daily WHERE stock_code='{ts_code}'
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
            FROM adj_factor WHERE stock_code='{ts_code}'
            ORDER BY trade_date
        """).fetchall()

        # 应用前复权
        closes, highs, lows = apply_forward_adjust(
            closes, highs, lows, adj_rows, dates
        )
        closes = np.array(closes, dtype=np.float64)

        # 估值数据（从 stock_valuation）
        val_rows = con.execute(f"""
            SELECT date, COALESCE(pe_ttm,0), COALESCE(pb,0), COALESCE(total_mv,0)
            FROM stock_valuation WHERE stock_code='{ts_code}'
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

        # 指数数据
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

            # 估值
            v_entry = val_map.get(dt, {})

            # 指数位置 (bisect 查找)
            idx_c = None
            if idx_dates is not None and dt in idx_dict:
                import bisect
                ip = bisect.bisect_left(idx_dates, dt)
                if ip < len(idx_dates) and idx_dates[ip] == dt and ip >= 20:
                    idx_c = [idx_dict[idx_dates[j]] for j in range(ip + 1)]

            # 特征计算
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

            # 标签
            label = closes[i + FWD_DAYS] / closes[i] - 1
            if label > 0.5 or label < -0.5:
                continue  # 异常值过滤

            X_raw.append(feat)
            y.append(label * 100.0)  # 转百分数
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

    # ── 随机80/20拆分 ──
    print(f"\nRandom 80/20 split (seed={SEED})...")
    rng = np.random.RandomState(SEED)
    indices = np.arange(len(X_raw))
    rng.shuffle(indices)
    split = int(0.8 * len(indices))
    train_idx = indices[:split]
    val_idx = indices[split:]

    X_train_raw = X_raw[train_idx]
    y_train = y[train_idx]
    X_val_raw = X_raw[val_idx]
    y_val = y[val_idx]
    print(f"  Train: {len(train_idx):,} ({len(train_idx)/len(indices)*100:.0f}%)")
    print(f"  Val:   {len(val_idx):,} ({len(val_idx)/len(indices)*100:.0f}%)")

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
        'num_leaves': 63, 'learning_rate': 0.03,
        'max_depth': 8,
        'feature_fraction': 0.7,
        'bagging_fraction': 0.8, 'bagging_freq': 5,
        'min_data_in_leaf': 100,
        'num_threads': 14,
        'device': 'cpu',
        'verbosity': -1,
    }

    dtrain = lgb.Dataset(X_train, y_train)
    dval = lgb.Dataset(X_val, y_val, reference=dtrain)

    model = lgb.train(params, dtrain, num_boost_round=500,
                      valid_sets=[dtrain, dval], valid_names=['train', 'val'],
                      callbacks=[lgb.early_stopping(20), lgb.log_evaluation(25)])

    best_iter = model.best_iteration
    model.save_model(str(OUT_MODEL), num_iteration=best_iter)

    # ── 评估 ──
    pred_train = model.predict(X_train, num_iteration=best_iter)
    pred_val = model.predict(X_val, num_iteration=best_iter)

    ic_train = stats.spearmanr(pred_train, y_train)[0]
    ic_val = stats.spearmanr(pred_val, y_val)[0]

    print(f"\n{'='*60}")
    print(f"40d-tushare Model Results")
    print(f"{'='*60}")
    print(f"Best trees: {best_iter}")
    print(f"Total features: {model.num_feature()}")
    print(f"Train IC: {ic_train:.4f}")
    print(f"Val IC:   {ic_val:.4f}")

    # 十分位回报
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

    # 特征重要性
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

    # 保存结果
    results = {
        'ic_val': round(float(ic_val), 4),
        'ic_train': round(float(ic_train), 4),
        'spread_pct': round(float(spread), 2),
        'hit_rate': round(float(hit_rate), 1),
        'best_trees': best_iter,
        'features': len(all_feat_names),
        'train_samples': len(X_train),
        'val_samples': len(X_val),
        'split': 'random_80_20',
        'seed': SEED,
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
