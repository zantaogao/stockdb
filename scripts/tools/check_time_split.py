"""快速时间切片 vs 随机拆分 IC 对比"""
import duckdb, numpy as np, lightgbm as lgb, sys, time, bisect
from pathlib import Path
from scipy import stats

sys.path.insert(0, '/Users/zantao/Desktop')
from feat_tushare import (
    get_tushare_db, load_index_data, get_board_index, apply_forward_adjust,
    compute_features, load_gtja, get_gtja_value,
    compute_norm_stats, standardize,
    FEAT_WIN, N_BASE, GTJA_CODES,
)

FWD_DAYS = 40
SEED = 42
MAX_SAMPLES = 200000
T0 = time.time()

idx_data = load_index_data()
gtja_lookups = load_gtja(GTJA_CODES)
con = get_tushare_db()

stock_codes = con.execute("""
    SELECT DISTINCT ts_code FROM daily
    WHERE trade_date >= '20150101' ORDER BY RANDOM() LIMIT 200
""").fetchall()
stock_codes = [r[0] for r in stock_codes]
print(f'Testing {len(stock_codes)} stocks...')

X_raw, y, date_of = [], [], []
samples = 0

for ts_code in stock_codes:
    code = ts_code.split('.')[0]
    rows = con.execute(f"""
        SELECT trade_date, close, high, low, COALESCE(pct_chg,0), vol
        FROM daily WHERE ts_code='{ts_code}' AND trade_date >= '20150101'
        ORDER BY trade_date
    """).fetchall()
    n = len(rows)
    if n < FEAT_WIN + FWD_DAYS + 1:
        continue
    dates = [str(r[0]) for r in rows]
    closes = [float(r[1]) for r in rows]
    highs = [float(r[2]) for r in rows]
    lows = [float(r[3]) for r in rows]
    pcts = [float(r[4])/100.0 for r in rows]
    volumes = [float(r[5]) for r in rows]

    adj_rows = con.execute(f"""
        SELECT trade_date, adj_factor FROM adj_factor
        WHERE ts_code='{ts_code}' ORDER BY trade_date
    """).fetchall()
    closes, highs, lows = apply_forward_adjust(closes, highs, lows, adj_rows, dates)
    closes = np.array(closes, dtype=np.float64)

    val_rows = con.execute(f"""
        SELECT trade_date, COALESCE(pe_ttm,0), COALESCE(pb,0), COALESCE(total_mv,0)
        FROM daily_basic WHERE ts_code='{ts_code}' ORDER BY trade_date
    """).fetchall()
    val_map = {}
    for dt, pe, pb, mv in val_rows:
        ds = str(dt)[:10]
        v = {}
        if float(pe) > 0: v['ep'] = 1.0/float(pe)
        if float(pb) > 0: v['bp'] = 1.0/float(pb)
        if float(mv) > 0: v['ln_cap'] = np.log(float(mv))
        val_map[ds] = v

    board_idx = get_board_index(ts_code)
    idx_info = idx_data.get(board_idx)
    idx_dates = idx_info['dates'] if idx_info else None
    idx_dict = idx_info['dict'] if idx_info else None

    for i in range(FEAT_WIN, n - FWD_DAYS):
        if closes[i] <= 0 or closes[i] < 2:
            continue
        dt = dates[i]
        if dt >= '20260618':
            continue
        v_entry = val_map.get(dt, {})
        idx_c = None
        if idx_dates is not None and dt in idx_dict:
            ip = bisect.bisect_left(idx_dates, dt)
            if ip < len(idx_dates) and idx_dates[ip] == dt and ip >= 20:
                idx_c = [idx_dict[idx_dates[j]] for j in range(ip+1)]

        feat = compute_features(closes[:i+1],
            np.array(highs[:i+1], dtype=np.float64),
            np.array(lows[:i+1], dtype=np.float64),
            np.array(volumes[:i+1], dtype=np.float64),
            np.array(pcts[:i+1], dtype=np.float64),
            idx_c, v_entry)

        gtja_vals = []
        for gn in GTJA_CODES:
            lookup = gtja_lookups.get(gn)
            gv = get_gtja_value(code, dt, lookup) if lookup else 0.0
            gtja_vals.append(gv)
        feat = np.append(feat, np.array(gtja_vals, dtype=np.float32))

        label = closes[i + FWD_DAYS] / closes[i] - 1
        if label > 0.5 or label < -0.5:
            continue

        X_raw.append(feat)
        y.append(label * 100.0)
        date_of.append(dt)
        samples += 1
        if samples >= MAX_SAMPLES:
            break
    if samples >= MAX_SAMPLES:
        break

con.close()
print(f'Samples: {len(X_raw):,}')
X_raw = np.array(X_raw, dtype=np.float32)
y = np.array(y, dtype=np.float64)
print(f'Label: mean={np.mean(y):+.2f}% std={np.std(y):.2f}%')

params = {'objective':'regression','metric':'l2','num_leaves':63,
          'learning_rate':0.03,'max_depth':8,'feature_fraction':0.7,
          'bagging_fraction':0.8,'bagging_freq':5,'min_data_in_leaf':100,
          'num_threads':4,'verbosity':-1}

# ═══ 随机80/20 ═══
print('\n--- Random 80/20 ---')
rng = np.random.RandomState(SEED)
indices = np.arange(len(X_raw))
rng.shuffle(indices)
split = int(0.8 * len(indices))

stats_dict = compute_norm_stats(X_raw[indices[:split]])
X_tr = standardize(X_raw[indices[:split]], stats_dict)
X_va = standardize(X_raw[indices[split:]], stats_dict)

model1 = lgb.train(params,
    lgb.Dataset(X_tr, y[indices[:split]]),
    num_boost_round=200,
    valid_sets=[lgb.Dataset(X_tr, y[indices[:split]]),
                lgb.Dataset(X_va, y[indices[split:]])],
    valid_names=['train','val'],
    callbacks=[lgb.early_stopping(20), lgb.log_evaluation(50)])

b1 = model1.best_iteration
ic1r = stats.spearmanr(model1.predict(X_tr, b1), y[indices[:split]])[0]
ic1v = stats.spearmanr(model1.predict(X_va, b1), y[indices[split:]])[0]
print(f'Random split ({b1} trees): IC_train={ic1r:.4f} IC_val={ic1v:.4f}')

# ═══ 时间切片 ═══
# 按日期分界：2024-01-01
date_arr = np.array(date_of)
train_mask = date_arr < '20240101'
val_mask = date_arr >= '20240101'

tr_sum = train_mask.sum()
va_sum = val_mask.sum()
print(f'\n--- Time split (train<2024, val>=2024) ---')
print(f'Train: {tr_sum:,} ({tr_sum/len(X_raw)*100:.0f}%)')
print(f'Val:   {va_sum:,} ({va_sum/len(X_raw)*100:.0f}%)')

stats_dict2 = compute_norm_stats(X_raw[train_mask])
X_tr2 = standardize(X_raw[train_mask], stats_dict2)
X_va2 = standardize(X_raw[val_mask], stats_dict2)

model2 = lgb.train(params,
    lgb.Dataset(X_tr2, y[train_mask]),
    num_boost_round=200,
    valid_sets=[lgb.Dataset(X_tr2, y[train_mask]),
                lgb.Dataset(X_va2, y[val_mask])],
    valid_names=['train','val'],
    callbacks=[lgb.early_stopping(20), lgb.log_evaluation(50)])

b2 = model2.best_iteration
ic2r = stats.spearmanr(model2.predict(X_tr2, b2), y[train_mask])[0]
ic2v = stats.spearmanr(model2.predict(X_va2, b2), y[val_mask])[0]
print(f'Time split ({b2} trees): IC_train={ic2r:.4f} IC_val={ic2v:.4f}')

print(f'\nTotal time: {time.time()-T0:.0f}s')
print('='*50)
print(f'随机拆分  IC_val={ic1v:.4f}')
print(f'时间切片  IC_val={ic2v:.4f}')
print(f'差异:     {ic1v - ic2v:.4f}')
print('='*50)
