"""LightGBM CLS 分类训练 — tushare数据源
- 20日5分类: [-5%, -1%, +1%, +5%]
- 时间切分 (train < 2025-01-01, val >= 2025-01-01)
- 27基础特征 + 4GTJA = 31维 (cls精简版，去掉ex5/10/20和rsi/adx/vpd/accel)
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
N_CLASSES = 5

# CLS 使用精简特征集（去掉 ex5/10/20 和 rsi/adx/vpd/trend_accel）
# 原因：分类对噪声敏感，保留核心量价+估值
CLS_BASE_FEATURES = [
    'chg5', 'chg10', 'chg20', 'chg60', 'chg120',
    'd5', 'd10', 'd20', 'd60', 'd120',
    'bull1', 'bull2', 'rr', 'std20', 'vr', 'pos',
    'nh', 'vpc', 'c1d', 'c3d', 'ep', 'bp', 'ln_cap',
    'ex5', 'ex10', 'ex20',
    'rsi14', 'adx14', 'vpd', 'trend_accel',
]
CLS_N_BASE = len(CLS_BASE_FEATURES)  # 30

# CLS用4个GTJA
CLS_GTJA = ['gtja_006', 'gtja_083']
CLS_ALL_FEATS = CLS_BASE_FEATURES + CLS_GTJA  # 32

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
OUT_MODEL = OUT_DIR / f'lgb_cls_tushare{_OUT_SUFFIX}.txt'
OUT_STATS = OUT_DIR / f'cls_tushare_norm_stats{_OUT_SUFFIX}.json'
OUT_RESULTS = OUT_DIR / f'train_cls_tushare_results{_OUT_SUFFIX}.json'

# 分类标签名称
CLASS_NAMES = ['大跌', '跌', '震荡', '涨', '大涨']

# ── 标签函数 ──
def cls_label(ret_pct):
    """收益率 -> 分类 0-4"""
    if ret_pct < -5: return 0
    if ret_pct < -1: return 1
    if ret_pct < 1:  return 2
    if ret_pct < 5:  return 3
    return 4

# ═══════════════════ 主流程 ═══════════════════

def main():
    t0 = time.time()
    print("=" * 60)
    print(f"CLS Classification — tushare data ({N_CLASSES} classes, 20d horizon)")
    print(f"  Features: {CLS_N_BASE} base + {len(CLS_GTJA)} GTJA = {len(CLS_ALL_FEATS)}")
    print(f"  Params: lr=0.05, leaves=63, depth=10, 200 rounds, ES=20")
    print(f"  Split: train < {SPLIT_DATE}")
    print("=" * 60)

    # ── 加载数据 ──
    print("\nLoading index data from stock.db...")
    idx_data = load_index_data()
    print(f"  Index codes loaded: {len(idx_data)}")

    print("Loading GTJA...")
    gtja_lookups = load_gtja(CLS_GTJA)
    print(f"  GTJA lookups: {len(gtja_lookups)}")

    con = get_tushare_db()

    stock_codes = [r[0] for r in con.execute(
        "SELECT DISTINCT ts_code FROM daily WHERE trade_date >= '20150101' ORDER BY ts_code"
    ).fetchall()]
    print(f"\nStocks: {len(stock_codes)}")

    # ── 数据构建 ──
    X_raw, y, date_list = [], [], []
    sample_count = 0

    for si, ts_code in enumerate(stock_codes):
        code = ts_code.split('.')[0]

        rows = con.execute(f"""
            SELECT trade_date, close, high, low, COALESCE(pct_chg,0), vol
            FROM daily WHERE ts_code='{ts_code}'
            AND trade_date >= '20150101'
            ORDER BY trade_date
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

        # 复权
        adj_rows = con.execute(f"""
            SELECT trade_date, adj_factor
            FROM adj_factor WHERE ts_code='{ts_code}'
            ORDER BY trade_date
        """).fetchall()
        closes, highs, lows = apply_forward_adjust(
            closes, highs, lows, adj_rows, dates
        )
        closes = np.array(closes, dtype=np.float64)

        # 估值
        val_rows = con.execute(f"""
            SELECT trade_date, COALESCE(pe_ttm,0), COALESCE(pb,0), COALESCE(total_mv,0)
            FROM daily_basic WHERE ts_code='{ts_code}'
            ORDER BY trade_date
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
            for gn in CLS_GTJA:
                lookup = gtja_lookups.get(gn)
                gv = get_gtja_value(code, dt, lookup) if lookup else 0.0
                gtja_vals.append(gv)
            feat = np.append(feat, np.array(gtja_vals, dtype=np.float32))

            # 标签（分类）
            label_pct = (closes[i + FWD_DAYS] / closes[i] - 1) * 100.0
            if label_pct > 30 or label_pct < -30:
                continue  # 极端异常值
            cls = cls_label(label_pct)

            X_raw.append(feat)
            y.append(cls)
            date_list.append(dt)
            sample_count += 1

        if (si + 1) % 500 == 0:
            print(f"  [{si+1}/{len(stock_codes)}] {sample_count:,} samples [{time.time()-t0:.0f}s]", flush=True)

    con.close()

    print(f"\nTotal samples: {len(X_raw):,}")
    X_raw = np.array(X_raw, dtype=np.float32)
    y = np.array(y, dtype=np.int32)
    print(f"Class distribution:")
    for c in range(N_CLASSES):
        cnt = np.sum(y == c)
        print(f"  {CLASS_NAMES[c]} ({c}): {cnt:,} ({cnt/len(y)*100:.0f}%)")

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
    print("\nTraining LightGBM (multiclass)...")
    params = {
        'objective': 'multiclass',
        'num_class': N_CLASSES,
        'metric': 'multi_logloss',
        'num_leaves': 63,
        'learning_rate': 0.05,
        'max_depth': 10,
        'feature_fraction': 0.7,
        'bagging_fraction': 0.8, 'bagging_freq': 5,
        'min_data_in_leaf': 200,
        'num_threads': 14,
        'verbosity': -1,
    }

    dtrain = lgb.Dataset(X_train, y_train)
    dval = lgb.Dataset(X_val, y_val, reference=dtrain)

    model = lgb.train(params, dtrain, num_boost_round=200,
                      valid_sets=[dtrain, dval], valid_names=['train', 'val'],
                      callbacks=[lgb.early_stopping(20), lgb.log_evaluation(10)])

    best_iter = model.best_iteration
    model.save_model(str(OUT_MODEL), num_iteration=best_iter)

    # ── 评估 ──
    prob_val = model.predict(X_val, num_iteration=best_iter)
    pred_val = np.argmax(prob_val, axis=1)
    prob_train = model.predict(X_train, num_iteration=best_iter)
    pred_train = np.argmax(prob_train, axis=1)

    acc_train = np.mean(pred_train == y_train) * 100
    acc_val = np.mean(pred_val == y_val) * 100
    print(f"\n{'='*60}")
    print(f"CLS-tushare Model Results ({N_CLASSES} classes)")
    print(f"{'='*60}")
    print(f"Best trees: {best_iter}")
    print(f"Train acc: {acc_train:.1f}%")
    print(f"Val acc:   {acc_val:.1f}%")

    # 混淆矩阵（简化版）
    print(f"\nConfusion matrix (val):")
    print(f"  {'':>6s}", end='')
    for c in range(N_CLASSES):
        print(f"  {CLASS_NAMES[c]:>5s}", end='')
    print()
    for true_c in range(N_CLASSES):
        print(f"  {CLASS_NAMES[true_c]:>6s}", end='')
        for pred_c in range(N_CLASSES):
            cnt = np.sum((y_val == true_c) & (pred_val == pred_c))
            print(f"  {cnt:>5d}", end='')
        print()

    # 各类准确率
    print(f"\nPer-class accuracy (val):")
    for c in range(N_CLASSES):
        mask = y_val == c
        if mask.sum() > 0:
            acc = np.mean(pred_val[mask] == c) * 100
            print(f"  {CLASS_NAMES[c]} ({c}): {acc:.1f}% ({mask.sum():,} samples)")

    # 特征重要性
    imp = model.feature_importance(importance_type='gain')
    total_imp = sum(imp)
    pairs = sorted(zip(CLS_ALL_FEATS, imp), key=lambda x: -x[1])
    print(f"\nTop 10 features (gain):")
    gtja_total = 0
    for fn, imp_v in pairs[:10]:
        pct = imp_v / total_imp * 100
        if 'gtja' in fn: gtja_total += pct
        print(f"  {fn:12s}: {pct:5.1f}%")
    print(f"  GTJA total: {gtja_total:.1f}%")

    results = {
        'val_acc': round(float(acc_val), 1),
        'train_acc': round(float(acc_train), 1),
        'best_trees': best_iter,
        'features': len(CLS_ALL_FEATS),
        'n_classes': N_CLASSES,
        'train_samples': len(X_train),
        'val_samples': len(X_val),
        'split_date': SPLIT_DATE,
        'time_sec': round(time.time() - t0),
    }
    with open(str(OUT_RESULTS), 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nSaved: {OUT_MODEL} ({best_iter} trees, val acc={acc_val:.1f}%)")
    print(f"Saved: {OUT_STATS}")
    print(f"Saved: {OUT_RESULTS}")
    print(f"Time: {time.time()-t0:.0f}s")

if __name__ == '__main__':
    main()
