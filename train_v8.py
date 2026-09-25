"""
v8 单一回归模型 — 精简化特征 + 年度滚动标准化 + 全周期训练
========================
特征集（18维）：
  基本面4: ep, bp, ln_cap, roe
  动量3: chg20, chg60, chg20_resid(对chg60的残差)
  偏离度3: d20, d60, pos20
  波动/量价4: std20, vr, vol_chg, rel_str
  形态3: c1d, dn_streak, up_ratio10
  GTJA4: gtja_006, gtja_083, gtja_177, gtja_184

训练策略：
  - train=2019-2023, val=2024, test=2025+
  - LightGBM: max_depth=5, early_stop=30

输出：
  models/lgb_reg_v8.txt          — 模型文件
  models/norm_stats_v8.json      — 标准化统计量
  models/train_result_v8.json    — 训练结果
"""
import os, json, gzip, pickle, time, numpy as np, lightgbm as lgb, bisect
from scipy import stats
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb')
DB = BASE / 'tushare.db'
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'

OUT_MODEL = BASE / 'models/lgb_reg_v8.txt'
OUT_STATS = BASE / 'models/norm_stats_v8.json'
OUT_RESULT = BASE / 'models/train_result_v8.json'

GTJA_4 = ['gtja_006', 'gtja_083', 'gtja_177', 'gtja_184']

FEAT_NAMES = [
    'ep', 'bp', 'ln_cap', 'roe',
    'chg20', 'chg60', 'chg20_resid',
    'd20', 'd60', 'pos20',
    'std20', 'vr', 'vol_chg', 'rel_str',
    'c1d', 'dn_streak', 'up_ratio10',
] + GTJA_4
N_FEATS = len(FEAT_NAMES)  # 21 (17 base + 4 GTJA)


def compute_raw_features(closes, amounts, volumes, returns, val_dict):
    """计算18维原始特征"""
    n = len(closes)
    if n < 120:
        return None

    lc = closes[-1]

    # ── 基本面 (4) ──
    ep = val_dict.get('ep', 0.5)
    bp = val_dict.get('bp', 0.5)
    ln_cap = val_dict.get('ln_cap', 22.0)
    roe = val_dict.get('roe', None)
    if roe is None or roe <= 0:
        roe = 0.3

    # ── 动量 (3) ──
    chg20 = lc / closes[-21] - 1 if n >= 21 else 0
    chg60 = lc / closes[-61] - 1 if n >= 61 else 0

    # chg20对chg60的残差（用过去120天窗口回归）
    resid = chg20  # default
    if n >= 180:
        c_w = closes[-120:]
        cg20_all, cg60_all = [], []
        for i in range(21, len(c_w)):
            cg20_all.append(c_w[i] / c_w[max(0, i-21)] - 1)
            cg60_all.append(c_w[i] / c_w[max(0, i-61)] - 1)
        if len(cg20_all) >= 30:
            x = np.array(cg60_all)
            y = np.array(cg20_all)
            mx, my = np.mean(x), np.mean(y)
            ss_xy = np.sum((x - mx) * (y - my))
            ss_xx = np.sum((x - mx)**2)
            if abs(ss_xx) > 1e-15:
                beta = ss_xy / ss_xx
                resid = chg20 - beta * chg60

    # ── 偏离度 (3) ──
    ma20 = np.mean(closes[-20:]) if n >= 20 else lc
    ma60 = np.mean(closes[-60:]) if n >= 60 else lc
    d20 = lc / ma20 - 1 if ma20 > 0 else 0
    d60 = lc / ma60 - 1 if ma60 > 0 else 0

    if n >= 20:
        c20 = closes[-20:]
        lo20, hi20 = min(c20), max(c20)
        pos20 = (lc - lo20) / (hi20 - lo20 + 1e-15) if hi20 > lo20 else 0.5
    else:
        pos20 = 0.5

    # ── 波动/量价 (4) ──
    std20 = np.std(closes[-20:]) / np.mean(closes[-20:]) * 100 if n >= 20 else 0

    vols_20 = volumes[-20:] if n >= 20 else [volumes[-1]]
    vr = volumes[-1] / (np.mean(vols_20) + 1e-15) if len(vols_20) > 0 and np.mean(vols_20) > 0 else 1.0

    if n >= 15:
        vol_recent = np.mean(volumes[-5:])
        vol_early = np.mean(volumes[-15:-5])
        vol_chg = vol_recent / (vol_early + 1e-15) - 1 if vol_early > 0 else 0
    else:
        vol_chg = 0

    # rel_str: stock 5d return vs long-term trend
    if n >= 6:
        stock_ret_5d = np.prod([1 + returns[-i] for i in range(1, 6)]) - 1
        lt_trend = (lc / closes[-61] - 1) * (5/60) if n >= 61 else 0
        rel_str = stock_ret_5d - lt_trend
    else:
        rel_str = 0

    # ── 形态 (3) ──
    c1d = returns[-1] if len(returns) > 0 else 0

    dn_streak = 0
    for i in range(len(returns)-1, max(-1, len(returns)-20), -1):
        if returns[i] < 0:
            dn_streak += 1
        else:
            break

    if n >= 10:
        up_ratio10 = sum(1 for r in returns[-10:] if r > 0) / 10.0
    else:
        up_ratio10 = 0.5

    return [ep, bp, ln_cap, roe, chg20, chg60, resid,
            d20, d60, pos20, std20, vr, vol_chg, rel_str,
            c1d, dn_streak, up_ratio10]


def get_gtja_value(code, date_str, gtja_lookup):
    """从gtja_compact中获取单个因子值"""
    if gtja_lookup is None:
        return 0.0
    dates = gtja_lookup['dates']
    df = gtja_lookup['df']
    if not dates or len(dates) == 0:
        return 0.0
    idx = bisect.bisect_right(dates, date_str[:10]) - 1
    if 0 <= idx < len(dates):
        d = dates[idx]
        try:
            val = float(df.loc[d, code])
            if not np.isnan(val):
                return val
        except Exception:
            pass
    return 0.0


def main():
    t0 = time.time()
    print("=" * 60)
    print("v8 Training — Single Regression Model")
    print("=" * 60)

    # ── 1. Load GTJA factors ──
    print("\n[1/5] Loading GTJA signals...")
    with gzip.open(str(GTJA_PKL), 'rb') as f:
        gtja_compact = pickle.load(f)

    gtja_lookups = {}
    for gn in GTJA_4:
        if gn in gtja_compact:
            df = gtja_compact[gn]
            dates = sorted([str(d)[:10] for d in df.index])
            gtja_lookups[gn] = {'dates': dates, 'df': df}
            print(f"  {gn}: {len(dates)} dates")
        else:
            gtja_lookups[gn] = None
            print(f"  {gn}: NOT FOUND")

    # ── 2. Load data from tushare.db ──
    import duckdb
    con = duckdb.connect(str(DB), read_only=True)

    all_codes = [r[0] for r in con.execute("""
        SELECT symbol FROM stock_basic 
        WHERE market != '北交所'
          AND list_date IS NOT NULL
    """).fetchall()]

    valid_codes = []
    for code in all_codes:
        cnt = con.execute(f"SELECT COUNT(*) FROM daily WHERE ts_code='{code}.SH' OR ts_code='{code}.SZ'").fetchone()[0]
        if cnt >= 120:
            valid_codes.append(code)

    print(f"\n[2/5] Loading daily data...")
    print(f"  Valid codes (>=120 days): {len(valid_codes)}")

    # Load valuation data from tushare.db daily_basic
    val_rows = con.execute("""
        SELECT ts_code, trade_date, pe_ttm, pb, total_mv 
        FROM daily_basic
    """).fetchall()
    vd = {}
    for ts_code, dt, pe, pb, mv in val_rows:
        code = ts_code.replace('.SH', '').replace('.SZ', '')
        dt_str = str(dt).replace('-', '')[:8] if '-' in str(dt) else str(dt)[:8]
        v = {}
        if pe and float(pe) > 0:
            try:
                v['ep'] = 1.0 / float(pe)
            except (ValueError, ZeroDivisionError):
                pass
        if pb and float(pb > 0):
            try:
                v['bp'] = 1.0 / float(pb)
            except (ValueError, ZeroDivisionError):
                pass
        if mv and float(mv) > 0:
            try:
                v['ln_cap'] = np.log(float(mv))
            except (ValueError, OverflowError):
                pass
        if v:
            vd[(code, dt_str)] = v

    print(f"  Valuation entries: {len(vd):,}")

    # Load ROE from fina_indicator
    roe_rows = con.execute("""
        SELECT ts_code, end_date, roe FROM fina_indicator
        WHERE roe IS NOT NULL AND roe != ''
    """).fetchall()
    roe_latest = {}
    for ts_code, dt, rv in roe_rows:
        code = ts_code.replace('.SH', '').replace('.SZ', '')
        dt_str = str(dt).replace('-', '')[:8] if '-' in str(dt) else str(dt)[:8]
        key = (code, dt_str)
        try:
            rv_val = float(rv) if rv is not None and rv != '' else 0
        except ValueError:
            continue
        if rv_val > 0:
            if key not in roe_latest or dt_str > list(roe_latest[key].keys())[0]:
                roe_latest[(code, dt_str)] = {dt_str: rv_val}

    # Merge latest ROE into valuation dict for each stock
    roe_by_stock = {}
    for (code, dt_str), val in roe_latest.items():
        if code not in roe_by_stock:
            roe_by_stock[code] = []
        for ydt, rv in val.items():
            roe_by_stock[code].append((ydt[:4], float(rv)))

    roe_yearly = {}
    for code, entries in roe_by_stock.items():
        year_groups = {}
        for yr_str, rv in entries:
            if yr_str not in year_groups or rv > year_groups[yr_str]:
                year_groups[yr_str] = rv
        sorted_years = sorted(year_groups.keys(), reverse=True)
        roe_yearly[code] = {yr: year_groups[yr] for yr in sorted_years}

    for (code, dt_str), v in vd.items():
        if code not in roe_yearly or 'roe' in v:
            continue
        year = int(dt_str[:4])
        best_roe = None
        for yr_str in sorted(roe_yearly[code].keys()):
            if int(yr_str) <= year:
                best_roe = roe_yearly[code][yr_str]
        if best_roe is not None and best_roe > 0:
            v['roe'] = best_roe

    # ── 3. Build feature matrix ──
    print("\n[3/5] Computing features...")
    X_raw_list, y_list, meta_list = [], [], []

    for ci, code in enumerate(valid_codes[:200]):
        ts_code = f"{code}.SH" if code.startswith(('6', '68', '9')) else f"{code}.SZ"
        rows = con.execute(f"""
            SELECT trade_date, close, amount, volume, pct_chg/100.0 as ret
            FROM daily 
            WHERE ts_code='{ts_code}' AND trade_date >= '20200101'
            ORDER BY trade_date
        """).fetchall()

        if len(rows) < 120:
            continue

        dates = [str(r[0])[:8] for r in rows]  # YYYYMMDD from tushare
        closes = np.array([float(r[1]) for r in rows], dtype=np.float64)
        amounts = np.array([float(r[2]) if r[2] else 0 for r in rows], dtype=np.float64)
        volumes = np.array([float(r[3]) if r[3] else 0 for r in rows], dtype=np.float64)
        returns_arr = np.array([float(r[4]) if r[4] is not None else 0 for r in rows], dtype=np.float64)

        for i in range(299, len(rows) - 20):
            dt_str = dates[i].replace('-', '')[:8]
            val_key = (code, dt_str)
            val_dict = vd.get(val_key, {})
            if not val_dict:
                continue

            feat_vec = compute_raw_features(
                closes[i-179:i+1], amounts[i-179:i+1],
                volumes[i-179:i+1], returns_arr[i-179:i+1], val_dict)

            if feat_vec is None:
                continue

            # Get GTJA values — dates in YYYYMMDD format
            gtja_vals = []
            for gn in GTJA_4:
                gv = get_gtja_value(code, dt_str, gtja_lookups[gn])
                gtja_vals.append(gv)

            all_feats = np.array(feat_vec + gtja_vals, dtype=np.float32)

            # Forward return (20 days)
            if i + 20 < len(closes):
                fwd_ret = closes[i+20] / closes[i] - 1
            else:
                continue

            X_raw_list.append(all_feats)
            y_list.append(fwd_ret * 100)
            meta_list.append({'code': code, 'date': dt_str, 'year': int(dt_str[:4])})

        if (ci + 1) % 50 == 0:
            print(f"  {ci+1}/{len(valid_codes)} stocks, {len(X_raw_list):,} samples")

    con.close()

    X_raw = np.array(X_raw_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.float32)

    print(f"\nTotal samples: {len(X_raw):,}")
    print(f"Features: {X_raw.shape[1]}")
    print(f"Label stats: mean={np.mean(y):+.2f}%, std={np.std(y):.2f}%")

    # Filter extreme returns
    valid_mask = (y > -50) & (y < 50)
    X_raw = X_raw[valid_mask]
    y = y[valid_mask]
    meta_list = [m for m, v in zip(meta_list, valid_mask) if v]
    print(f"After filtering: {len(X_raw):,} samples")

    # ── 4. Train/Val/Test split by year + normalization ──
    print("\n[4/5] Splitting and normalizing...")

    years = np.array([m['year'] for m in meta_list])

    train_mask = years <= 2023
    val_mask = (years == 2024)
    test_mask = years >= 2025

    X_train_raw, y_train = X_raw[train_mask], y[train_mask]
    X_val_raw, y_val = X_raw[val_mask], y[val_mask]
    X_test_raw, y_test = X_raw[test_mask], y[test_mask]

    print(f"  Train (<=2023): {len(X_train_raw):,}")
    print(f"  Val   (2024):   {len(X_val_raw):,}")
    print(f"  Test  (>=2025): {len(X_test_raw):,}")

    # Normalize from training data only
    norm_stats = {}
    for j in range(N_FEATS):
        col = X_train_raw[:, j]
        valid = col[~np.isnan(col)]
        if len(valid) < 10:
            mean_j, std_j, lo, hi = 0.0, 1.0, -10.0, 10.0
        else:
            lo, hi = np.percentile(valid, 1), np.percentile(valid, 99)
            mean_j, std_j = np.mean(valid), np.std(valid)

        norm_stats[j] = {'mean': float(mean_j), 'std': float(std_j), 'low': float(lo), 'high': float(hi)}

    def apply_norm(X):
        Xn = X.copy()
        for j in range(X.shape[1]):
            s = norm_stats[j]
            col = np.clip(X[:, j], s['low'], s['high'])
            if s['std'] > 1e-10:
                Xn[:, j] = (col - s['mean']) / s['std']
        return np.nan_to_num(Xn)

    X_train = apply_norm(X_train_raw)
    X_val = apply_norm(X_val_raw)
    X_test = apply_norm(X_test_raw)

    # Save norm stats
    stats_out = {}
    for j in range(N_FEATS):
        s = norm_stats[j]
        stats_out[f'feat_{j}'] = {'name': FEAT_NAMES[j], **s}
    with open(OUT_STATS, 'w') as f:
        json.dump(stats_out, f, indent=2)
    print(f"  Norm stats saved")

    # ── 5. Train LightGBM ──
    print("\n[5/5] Training LightGBM...")

    dtrain = lgb.Dataset(X_train, y_train)
    dval = lgb.Dataset(X_val, y_val, reference=dtrain)

    params = {
        'objective': 'regression',
        'metric': 'l2',
        'num_leaves': 31,
        'learning_rate': 0.02,
        'feature_fraction': 0.7,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'min_data_in_leaf': 100,
        'max_depth': 5,
        'verbose': -1,
        'num_threads': -1,
        'lambda_l1': 0.1,
        'lambda_l2': 0.1,
    }

    model = lgb.train(
        params, dtrain, num_boost_round=3000,
        valid_sets=[dtrain, dval],
        valid_names=['train', 'val'],
        callbacks=[lgb.early_stopping(30), lgb.log_evaluation(100)]
    )

    best_iter = model.best_iteration
    print(f"  Best iteration: {best_iter}")

    # ── 6. Evaluate ──
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    pred_train = model.predict(X_train, num_iteration=best_iter)
    pred_val = model.predict(X_val, num_iteration=best_iter)
    pred_test = model.predict(X_test, num_iteration=best_iter)

    ic_train = stats.spearmanr(pred_train, y_train)[0]
    ic_val = stats.spearmanr(pred_val, y_val)[0]
    ic_test = stats.spearmanr(pred_test, y_test)[0]

    print(f"\nIC (Spearman):")
    print(f"  Train: {ic_train:.4f}")
    print(f"  Val:   {ic_val:.4f}")
    print(f"  Test:  {ic_test:.4f}")

    # Decile analysis on test set
    df_test = pd.DataFrame({'pred': pred_test, 'ret': y_test})
    df_test['decile'] = pd.qcut(df_test['pred'].rank(method='first'), 10, labels=False, duplicates='drop')
    grp = df_test.groupby('decile')['ret'].mean()
    
    print(f"\nTest Decile Analysis:")
    for d in range(len(grp)):
        print(f"  D{d+1}: {grp.iloc[d]:+.2f}%")
    
    spread = grp.iloc[-1] - grp.iloc[0] if len(grp) > 1 else 0
    mono = all(grp.iloc[i] <= grp.iloc[i+1] for i in range(len(grp)-1)) if len(grp) > 1 else False
    
    print(f"\n  Spread (D10-D1): {spread:+.2f}%")
    print(f"  Monotonicity: {'PASS' if mono else 'FAIL'}")

    # Feature importance
    imp = model.feature_importance(importance_type='gain')
    total_imp = sum(imp)
    top10_idx = np.argsort(imp)[-10:][::-1]
    
    print(f"\nTop 10 Features (importance):")
    for j in top10_idx:
        nm = FEAT_NAMES[j] if j < len(FEAT_NAMES) else f'feat_{j}'
        pct = imp[j] / total_imp * 100 if total_imp > 0 else 0
        print(f"  {nm:20s}: {pct:.1f}%")

    # Save model
    model.save_model(str(OUT_MODEL), num_iteration=best_iter)
    print(f"\nModel saved to {OUT_MODEL}")

    # Save results
    result = {
        'model': str(OUT_MODEL.name),
        'feats': N_FEATS,
        'trees': best_iter,
        'split_train': '<=2023',
        'split_val': '2024',
        'split_test': '>=2025',
        'train_ic': round(float(ic_train), 4),
        'val_ic': round(float(ic_val), 4),
        'test_ic': round(float(ic_test), 4),
        'test_spread': round(float(spread), 2),
        'monotonic': mono,
        'time_sec': round(time.time() - t0, 0),
    }

    with open(OUT_RESULT, 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"\nResults saved to {OUT_RESULT}")
    print(f"Total time: {time.time()-t0:.0f}s")


if __name__ == '__main__':
    import pandas as pd
    main()
