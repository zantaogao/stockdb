#!/usr/bin/env python3
"""
40日回归模型重训 v2
=====================
本地 Mac 训练，数据源 tushare.db。
使用与 scoring.py 完全一致的特征管线（feat_tushare 29维）。

目标：控树数到 100-200 棵，降低过拟合，提升验证 IC。

训练策略：
  时间切分: 训练2022-01~2026-06 / 验证2026-07
  特征标准化: 从训练集统计
  早停: 验证集 IC 不提升则停
  目标: 40日前向收益
  正则: L1+L2=1.5, min_data=80, feature_fraction=0.7（比10d更保守）

用法:
  python3 scripts/train_40d_local.py               # 全量训练
  python3 scripts/train_40d_local.py --quick        # 快速测试（500只×6个月）
"""
import argparse, json, sys, time, random
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.hermes/stockdb'))

import duckdb
import numpy as np
import lightgbm as lgb
from scipy import stats
from core.db import TUSHARE_DB_PATH, get_tushare_db
sys.path.insert(0, str(Path.home() / '.hermes/stockdb/scripts'))
from feat_tushare import compute_features, apply_forward_adjust, get_board_index, get_factor_from_db

OUT_DIR = Path.home() / '.hermes' / 'stockdb' / 'models'
MODEL_PATH = OUT_DIR / 'lgb_reg_40d_v2.txt'
STATS_PATH = OUT_DIR / 'v6_norm_stats_40d_v2.json'
RESULT_PATH = OUT_DIR / 'train_40d_v2_result.json'

FWD_DAYS = 40
TRAIN_SPLIT = '2026-07-01'
MIN_DAYS = 200  # 40日模型需要更多历史

STK_FACTORS = ['kdj_k', 'cci', 'rsi_12']

_idx_cache = {}


def load_idx_data():
    if _idx_cache:
        return _idx_cache
    from feat_tushare import get_board_index
    src = get_tushare_db()
    for idx_name in ['000001.SH', '399001.SZ', '399006.SZ']:
        rows = src.execute(
            "SELECT trade_date, close FROM daily WHERE ts_code=? ORDER BY trade_date", [idx_name]
        ).fetchall()
        if rows:
            dates = [str(r[0]) for r in rows]
            prices = {str(r[0]): float(r[1]) for r in rows}
            _idx_cache[idx_name] = {'dates': dates, 'dict': prices}
    src.close()
    return _idx_cache


def extract_features(code, conn, as_of_date, min_days=200):
    """同 scoring._compute_ml_features"""
    ts_code_full = f"{code}.SH" if code.startswith(('6', '68', '9')) else f"{code}.SZ"
    rows = conn.execute(f"""
        SELECT trade_date, close, open, high, low, COALESCE(pct_chg,0), vol, amount
        FROM daily WHERE ts_code='{ts_code_full}' AND trade_date <= '{as_of_date}'
        ORDER BY trade_date DESC LIMIT {min_days + 100}
    """).fetchall()
    if not rows or len(rows) < min_days:
        return None
    rows = rows[::-1]
    closes = [float(r[1]) for r in rows]
    highs_raw = [float(r[3]) for r in rows]
    lows_raw = [float(r[4]) for r in rows]
    pcts = [float(r[5]) / 100.0 for r in rows]
    volumes = [float(r[6]) for r in rows]
    dates_str = [str(r[0])[:10] for r in rows]
    adj_rows = conn.execute(
        "SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date", [ts_code_full]
    ).fetchall()
    adj_closes, adj_highs, adj_lows = apply_forward_adjust(closes, highs_raw, lows_raw, adj_rows)
    # 转为 list（compute_features 内部需要）
    adj_closes = list(adj_closes) if hasattr(adj_closes, '__iter__') else adj_closes
    adj_highs = list(adj_highs) if hasattr(adj_highs, '__iter__') else adj_highs
    adj_lows = list(adj_lows) if hasattr(adj_lows, '__iter__') else adj_lows
    idx_data = load_idx_data()
    board_idx = get_board_index(code)
    idx_info = idx_data.get(board_idx)
    idx_closes = None
    if idx_info and dates_str[-1] in idx_info['dict']:
        import bisect
        ip = bisect.bisect_left(idx_info['dates'], dates_str[-1])
        if ip >= 20 and ip < len(idx_info['dates']):
            idx_closes = [idx_info['dict'][idx_info['dates'][j]] for j in range(ip + 1)]
    val_row = conn.execute(
        "SELECT pe_ttm, pb, total_mv FROM daily_basic WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1",
        [ts_code_full]
    ).fetchone()
    val_dict = {}
    if val_row:
        pe, pb, mv = val_row
        if pe and float(pe) > 0: val_dict['ep'] = 1.0 / float(pe)
        if pb and float(pb) > 0: val_dict['bp'] = 1.0 / float(pb)
        if mv and float(mv) > 0: val_dict['ln_cap'] = np.log(float(mv))
    feat = compute_features(adj_closes, adj_highs, adj_lows, volumes, pcts, idx_closes, val_dict)
    if feat is None:
        return None
    kept = [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,21,22,23,24,25,26]
    feat_selected = np.array([feat[i] for i in kept], dtype=np.float64)
    dt_clean = as_of_date.replace('-', '')
    factor_vals = []
    for fn in STK_FACTORS:
        v = get_factor_from_db(code, dt_clean, [fn], conn)
        factor_vals.append(float(v.get(fn, 0.0)))
    return np.append(feat_selected, np.array(factor_vals, dtype=np.float64))


def get_forward_return(conn, code, trade_date, days=40):
    ts_code_full = f"{code}.SH" if code.startswith(('6', '68', '9')) else f"{code}.SZ"
    r = conn.execute(f"""
        SELECT b.close / a.close - 1
        FROM daily a JOIN (
            SELECT ts_code, trade_date, close,
                   ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date) as rn
            FROM daily WHERE ts_code = '{ts_code_full}' AND trade_date > '{trade_date}'
        ) b ON a.ts_code = b.ts_code AND b.rn = {days}
        WHERE a.ts_code = '{ts_code_full}' AND a.trade_date = '{trade_date}'
    """).fetchone()
    return float(r[0]) if r and r[0] else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--quick', action='store_true')
    args = parser.parse_args()

    print('=' * 55)
    print('LightGBM 40日回归重训 v2（防过拟合版）')
    print('=' * 55)

    conn = get_tushare_db()
    load_idx_data()

    all_codes = [r[0] for r in conn.execute(
        "SELECT ts_code FROM daily WHERE trade_date = (SELECT MAX(trade_date) FROM daily) "
        "AND ts_code NOT LIKE '%ST%'"
    ).fetchall()]

    if args.quick:
        random.seed(42)
        codes = random.sample(all_codes, 500)
        fwd_days = 10
        trade_dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT trade_date FROM daily WHERE trade_date > '20250601' ORDER BY trade_date"
        ).fetchall()]
        trade_dates = [d for d in trade_dates if d < trade_dates[-fwd_days-5]]
        local_min_days = 120
        split = trade_dates[len(trade_dates)//2]  # 以中点为切分
        print(f'快速: {len(codes)}只, {len(trade_dates)}天, fwd={fwd_days}, split={split}')
    else:
        codes = all_codes[:2000]
        fwd_days = FWD_DAYS
        trade_dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT trade_date FROM daily WHERE trade_date > '20220101' ORDER BY trade_date"
        ).fetchall()]
        trade_dates = [d for d in trade_dates if d < trade_dates[-fwd_days-5]]
        local_min_days = MIN_DAYS
        print(f'全量: {len(codes)}只, {len(trade_dates)}天, fwd={fwd_days}, min_days={local_min_days}')

    split_val = trade_dates[len(trade_dates)//2]  # 中点切分
    train_dates = [d for d in trade_dates if d < split_val]
    val_dates = [d for d in trade_dates if d >= split_val]
    print(f'切分点: {split_val}  训练: {len(train_dates)}天  验证: {len(val_dates)}天')

    print('\n提取训练样本...')
    X_train, y_train = [], []
    X_val, y_val = [], []
    n_skip = 0

    for idx, code in enumerate(codes):
        base = code.replace('.SH', '').replace('.SZ', '')
        if (idx + 1) % 100 == 0:
            print(f'  进度: {idx+1}/{len(codes)} (跳过{n_skip})')

        for dt_list, X_list, y_list in [
            (train_dates, X_train, y_train),
            (val_dates, X_val, y_val)
        ]:
            dt = dt_list[-1] if dt_list else None
            if dt is None:
                continue
            feat = extract_features(base, conn, dt, local_min_days)
            if feat is None:
                n_skip += 1
                continue
            fwd = get_forward_return(conn, base, dt, fwd_days)
            if fwd is None:
                n_skip += 1
                continue
            X_list.append(feat)
            y_list.append(fwd)

    X_train = np.array(X_train, dtype=np.float64)
    X_val = np.array(X_val, dtype=np.float64)
    y_train = np.array(y_train, dtype=np.float64)
    y_val = np.array(y_val, dtype=np.float64)

    print(f'\n样本: 训练={len(X_train)}  验证={len(X_val)}  跳过={n_skip}')
    print(f'特征维度: {X_train.shape[1]}')

    min_val = 10 if args.quick else 50
    if len(X_train) < 100 or len(X_val) < min_val:
        print(f'样本不足: train={len(X_train)}, val={len(X_val)}（需要至少{min_val}验证样本）')
        conn.close()
        return

    # 标准化
    norm_stats = {}
    for j in range(X_train.shape[1]):
        col = X_train[:, j]
        mean, std = float(np.mean(col)), float(np.std(col, ddof=1))
        low = float(np.percentile(col, 1))
        high = float(np.percentile(col, 99))
        norm_stats[f'feat_{j}'] = {'mean': mean, 'std': std, 'low': low, 'high': high}
        if std > 0:
            X_train[:, j] = np.clip(X_train[:, j], low, high)
            X_train[:, j] = (X_train[:, j] - mean) / std
            X_val[:, j] = np.clip(X_val[:, j], low, high)
            X_val[:, j] = (X_val[:, j] - mean) / std

    # 训练（保守参数防过拟合）
    print('\n开始训练...')
    # 快速模式用宽松参数，全量模式用保守参数
    if args.quick:
        params = {
            'objective': 'regression_l2', 'metric': 'l2_root',
            'boosting_type': 'gbdt', 'num_leaves': 15,
            'learning_rate': 0.1, 'feature_fraction': 0.8,
            'bagging_fraction': 0.8, 'bagging_freq': 5,
            'lambda_l1': 0.1, 'lambda_l2': 0.1, 'min_data_in_leaf': 20,
            'verbose': -1, 'seed': 42,
        }
    else:
        params = {
            'objective': 'regression_l2', 'metric': 'l2_root',
            'boosting_type': 'gbdt', 'num_leaves': 31,
            'learning_rate': 0.08, 'feature_fraction': 0.8,
            'bagging_fraction': 0.8, 'bagging_freq': 5,
            'lambda_l1': 0.5, 'lambda_l2': 0.5, 'min_data_in_leaf': 50,
            'verbose': -1, 'seed': 42,
        }
        print('  参数: 中等正则 (L1/L2=0.5, lr=0.08, min_data=50)')

    def ic_metric(preds, train_data):
        y_true = train_data.get_label()
        if len(preds) < 30 or np.std(preds) == 0:
            return 'rank_ic', 0.0, False
        rho, _ = stats.spearmanr(preds, y_true)
        return 'rank_ic', float(rho), True

    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

    model = lgb.train(
        params, train_data,
        num_boost_round=300,         # 上限300
        valid_sets=[val_data],
        feval=ic_metric,
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(50)]
    )

    n_trees = model.num_trees()
    print(f'\n训练完成: {n_trees}棵树')

    pred_train = model.predict(X_train)
    pred_val = model.predict(X_val)
    ic_train, _ = stats.spearmanr(pred_train, y_train)
    ic_val, _ = stats.spearmanr(pred_val, y_val)
    print(f'\n训练集 Rank IC: {ic_train:+.4f}')
    print(f'验证集 Rank IC: {ic_val:+.4f}')
    print(f'训练/验证差距: {ic_train - ic_val:.4f}')

    model.save_model(str(MODEL_PATH))
    with open(STATS_PATH, 'w') as f:
        json.dump(norm_stats, f, ensure_ascii=False, indent=2)

    result = {
        'n_trees': n_trees,
        'n_features': X_train.shape[1],
        'n_train': len(X_train), 'n_val': len(X_val),
        'ic_train': round(float(ic_train), 4),
        'ic_val': round(float(ic_val), 4),
        'params': params,
    }
    with open(RESULT_PATH, 'w') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'\n模型: {MODEL_PATH}')
    print(f'标准化: {STATS_PATH}')
    print(f'结果: {RESULT_PATH}')
    if ic_val > 0.15:
        print('✅ 验证IC > 0.15，优于旧模型')
    else:
        print('⚠️ 验证IC偏低，可能需调整参数')

    conn.close()


if __name__ == '__main__':
    main()
