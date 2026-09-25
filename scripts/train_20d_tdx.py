"""LightGBM 20d 回归训练 — TDX数据源（新数据库）
|- 20日收益预测
|- 时间切分 (train < 2025-01-01, val >= 2025-01-01)
|- 30基础特征 + 2GTJA + 3市场特征 = 35维
|- 新增：波动率区间、指数ADX、行业轮动信号
|- TDX数据（已复权，无需adj_factor）
|- 行业/GTJA/估值仍从tushare加载
"""
import os, json, time, sys
import numpy as np
import lightgbm as lgb
from pathlib import Path
from scipy import stats

sys.stdout.reconfigure(line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent))
from feat_tushare import (
    get_tushare_db, get_tdx_db, ts_code_to_tdx,
    load_index_data_tdx, get_board_index,
    compute_features, load_gtja, get_gtja_value,
    compute_norm_stats, standardize,
    compute_market_features_tdx,
    FEAT_WIN, BASE_FEAT_NAMES, N_BASE, GTJA_CODES,
    MKT_FEAT_NAMES, N_MKT,
)

# ── 配置 ──
FWD_DAYS = 20
ALL_FEAT_NAMES = BASE_FEAT_NAMES + GTJA_CODES + MKT_FEAT_NAMES
N_FEATS = N_BASE + len(GTJA_CODES) + N_MKT  # 35

# 时间切分
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
OUT_MODEL = OUT_DIR / f'lgb_reg_20d_tdx{_OUT_SUFFIX}.txt'
OUT_STATS = OUT_DIR / f'v6_norm_stats_20d_tdx{_OUT_SUFFIX}.json'
OUT_RESULTS = OUT_DIR / f'train_20d_tdx_results{_OUT_SUFFIX}.json'

# ═══════════════════ 主流程 ═══════════════════

def main():
    t0 = time.time()
    print("=" * 60)
    print(f"20d Regression — TDX datasource")
    print(f"  Features: {N_BASE} base + {len(GTJA_CODES)} GTJA + {N_MKT} mkt = {N_FEATS}")
    print(f"  Feature names: {ALL_FEAT_NAMES}")
    print(f"  Params: lr=0.03, leaves=63, depth=8, 200 rounds, ES=30")
    print(f"  Split: train < {SPLIT_DATE}")
    print("=" * 60)

    # ── 加载数据 ──
    print("\nLoading index data (TDX)...")
    idx_data = load_index_data_tdx()
    print(f"  Index codes loaded: {len(idx_data)}")

    print("Loading GTJA...")
    gtja_lookups = load_gtja(GTJA_CODES)
    print(f"  GTJA lookups: {len(gtja_lookups)}")

    # 连接两个数据库
    con_ts = get_tushare_db()  # 用于行业/估值/stock列表
    con_tdx = get_tdx_db()      # 用于日线数据

    # 股票列表
    stock_codes = [r[0] for r in con_ts.execute(
        "SELECT DISTINCT ts_code FROM daily WHERE trade_date >= '20150101' ORDER BY ts_code"
    ).fetchall()]
    print(f"\nStocks: {len(stock_codes)}")

    # ── 预计算市场特征 ──
    print("Computing market-level features (vol/ADX/industry rotation)...")
    all_dates = [r[0] for r in con_ts.execute(
        "SELECT DISTINCT trade_date FROM daily WHERE trade_date >= '20150101' ORDER BY trade_date"
    ).fetchall()]
    all_dates = [str(d)[:10] for d in all_dates]
    mkt_feats = compute_market_features_tdx(all_dates)
    print(f"  Market features computed for {len(mkt_feats)} dates")

    # ── 数据构建 ──
    X_raw, y, date_list = [], [], []
    sample_count = 0

    for si, ts_code in enumerate(stock_codes):
        code, market = ts_code_to_tdx(ts_code)  # '000001', 'sz'

        # 从TDX加载日线（已复权，无pct_chg）
        rows = con_tdx.execute(f"""
            SELECT date, close, high, low, amount, volume
            FROM daily WHERE code='{code}' AND market='{market}'
            ORDER BY date
        """).fetchall()
        n = len(rows)
        if n < FEAT_WIN + FWD_DAYS + 1:
            continue

        dates = [str(r[0]) for r in rows]
        closes_f = [float(r[1]) for r in rows]
        highs_f = [float(r[2]) for r in rows]
        lows_f = [float(r[3]) for r in rows]
        volumes_f = [float(r[5]) for r in rows]  # volume, index 4 is amount

        # 计算涨跌幅
        closes_arr = np.array(closes_f, dtype=np.float64)
        pcts = np.zeros(n)
        pcts[1:] = (closes_arr[1:] - closes_arr[:-1]) / closes_arr[:-1]

        # 估值（从tushare）
        val_rows = con_ts.execute(f"""
            SELECT trade_date, COALESCE(pe_ttm,0), COALESCE(pb,0), COALESCE(total_mv,0)
            FROM daily_basic WHERE ts_code='{ts_code}' ORDER BY trade_date
        """).fetchall()
        val_map = {}
        for dt, pe, pb, mv in val_rows:
            ds = str(dt)[:10]
            v = {}
            if float(pe) > 0: v['ep'] = 1.0 / float(pe)
            if float(pb) > 0: v['bp'] = 1.0 / float(pb)
            if float(mv) > 0: v['ln_cap'] = np.log(float(mv))
            val_map[ds] = v

        # 板块指数（TDX）
        board_idx = get_board_index(ts_code)
        idx_info = idx_data.get(board_idx)
        idx_dates = idx_info['dates'] if idx_info else None
        idx_dict = idx_info['dict'] if idx_info else None

        for i in range(FEAT_WIN, n - FWD_DAYS):
            if closes_arr[i] <= 0 or closes_arr[i] < 2:
                continue
            dt = dates[i]
            if dt >= '20260618':
                continue

            v_entry = val_map.get(dt, {})

            # 指数位置
            idx_c = None
            if idx_dates is not None and dt in idx_dict:
                ip = __import__('bisect').bisect_left(idx_dates, dt)
                if ip < len(idx_dates) and idx_dates[ip] == dt and ip >= 20:
                    idx_c = [idx_dict[idx_dates[j]] for j in range(ip + 1)]

            # 基础特征
            feat = compute_features(
                closes_arr[:i+1], np.array(highs_f[:i+1], dtype=np.float64),
                np.array(lows_f[:i+1], dtype=np.float64),
                np.array(volumes_f[:i+1], dtype=np.float64),
                pcts[:i+1], idx_c, v_entry
            )

            # GTJA
            for gn in GTJA_CODES:
                lookup = gtja_lookups.get(gn)
                gv = get_gtja_value(code, dt, lookup) if lookup else 0.0
                feat = np.append(feat, gv)

            # 市场特征
            mf = mkt_feats.get(dt, [0.0, 25.0, 0.0])
            feat = np.append(feat, np.array(mf, dtype=np.float32))

            # 标签
            label = closes_arr[i + FWD_DAYS] / closes_arr[i] - 1
            if label > 0.5 or label < -0.5:
                continue

            X_raw.append(feat)
            y.append(label * 100.0)
            date_list.append(dt)
            sample_count += 1

        if (si + 1) % 500 == 0:
            print(f"  [{si+1}/{len(stock_codes)}] {sample_count:,} samples [{time.time()-t0:.0f}s]", flush=True)

    con_ts.close()
    con_tdx.close()
    print(f"\nTotal samples: {sample_count:,}")

    X_raw = np.array(X_raw, dtype=np.float32)
    y = np.array(y, dtype=np.float64)

    # ── 标签分布 ──
    print(f"\nLabel distribution:")
    print(f"  mean={np.mean(y):+.2f}% std={np.std(y):.2f}%")
    for p in [1, 5, 25, 50, 75, 95, 99]:
        print(f"  P{p}: {np.percentile(y, p):+.2f}%")

    # ── 切片 ──
    date_arr = np.array(date_list)
    train_mask = date_arr < SPLIT_DATE
    val_mask = date_arr >= SPLIT_DATE

    X_train = X_raw[train_mask]
    y_train = y[train_mask]
    X_val = X_raw[val_mask]
    y_val = y[val_mask]

    print(f"\nTrain: {len(X_train):,} (before {SPLIT_DATE})")
    print(f"Val:   {len(X_val):,} (on/after {SPLIT_DATE})")

    # ── 标准化 ──
    print("\nComputing normalization stats (train only)...")
    norm_stats = compute_norm_stats(X_train)
    X_train_s = standardize(X_train, norm_stats)
    X_val_s = standardize(X_val, norm_stats)

    with open(OUT_STATS, 'w') as f:
        json.dump(norm_stats, f, indent=2)
    print(f"  Stats saved: {OUT_STATS}")

    # ── 训练 ──
    params = {
        'objective': 'regression',
        'metric': 'l2',
        'num_leaves': 63,
        'learning_rate': 0.03,
        'max_depth': 8,
        'feature_fraction': 0.7,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'min_data_in_leaf': 100,
        'num_threads': 8,
        'verbosity': -1,
    }

    print("\nTraining LightGBM...")
    dt = lgb.Dataset(X_train_s, y_train)
    dv = lgb.Dataset(X_val_s, y_val, reference=dt)
    model = lgb.train(
        params, dt,
        num_boost_round=200,
        valid_sets=[dt, dv],
        valid_names=['train', 'val'],
        callbacks=[lgb.early_stopping(30), lgb.log_evaluation(25)],
    )

    bi = model.best_iteration
    pred_train = model.predict(X_train_s, num_iteration=bi)
    pred_val = model.predict(X_val_s, num_iteration=bi)

    ic_train = float(stats.spearmanr(pred_train, y_train)[0])
    ic_val = float(stats.spearmanr(pred_val, y_val)[0])

    # 分组收益
    order = np.argsort(pred_val)
    n_val = len(order)
    d1 = np.mean(y_val[order[:n_val//10]])
    d10 = np.mean(y_val[order[-n_val//10:]])
    spread = d10 - d1
    hit_rate = np.mean(y_val[order[-n_val//10:]] > 0) * 100

    print(f"\n{'='*60}")
    print(f"20d-TDX Model Results")
    print(f"{'='*60}")
    print(f"Best trees: {bi}")
    print(f"IC train:   {ic_train:.4f}")
    print(f"IC val:     {ic_val:.4f}")
    print(f"Spread:     {spread:+.2f}%")
    print(f"D10 hit:    {hit_rate:.0f}%")

    # 特征重要性
    imp = model.feature_importance(importance_type='gain')
    total_gain = sum(imp)
    pairs = [(ALL_FEAT_NAMES[i], imp[i], imp[i]/total_gain*100) for i in range(N_FEATS)]
    pairs.sort(key=lambda x: -x[2])
    print(f"\nTop 15 features (gain):")
    for name, v, pct in pairs[:15]:
        print(f"  {name:15s}  {pct:5.1f}%")
    gtja_pct = sum(p[2] for p in pairs if p[0].startswith('gtja'))
    mkt_pct = sum(p[2] for p in pairs if p[0] in MKT_FEAT_NAMES)
    ex_pct = sum(p[2] for p in pairs if p[0].startswith('ex'))
    print(f"  {'─'*25}")
    print(f"  GTJA total:   {gtja_pct:5.1f}%")
    print(f"  Market feat:  {mkt_pct:5.1f}%")
    print(f"  Excess ret:   {ex_pct:5.1f}%")

    # 保存
    model.save_model(str(OUT_MODEL))
    results = {
        'ic_val': round(ic_val, 4), 'ic_train': round(ic_train, 4),
        'spread_pct': round(spread, 2), 'hit_rate': round(hit_rate, 1),
        'best_trees': bi, 'features': N_FEATS,
        'train_samples': len(X_train), 'val_samples': len(X_val),
        'split_date': SPLIT_DATE, 'time_sec': round(time.time() - t0),
    }
    with open(OUT_RESULTS, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nSaved: {OUT_MODEL} ({bi} trees, IC={ic_val:.4f})")
    print(f"Saved: {OUT_RESULTS}")
    print(f"Time: {time.time()-t0:.0f}s")

if __name__ == '__main__':
    main()
