#!/usr/bin/env python3
"""
40d 增量训练（2026-08-07 规划实施）
=====================================
在保留 10 年数据基础（生产旧模型，已验证 IC 有效）的前提下，吸收旧模型未见过的
最新样本——避免全量重训（2022 起）的信号重构（实证 v2/v3 vs 旧模型 Spearman 仅 0.35）。

关键设计（对齐规划）：
1. init_model = 生产旧模型 lgb_reg_40d_new_stkfactor.txt（500 树，10 年数据）
2. 特征标准化用【旧 stats】（v6_norm_stats_40d_tushare_v2_stkfactor.json）——保持特征空间
   与旧树一致，新树在同空间学习；部署后推理侧 stats 路径不变
3. 增量数据 = 旧模型没见过的样本：特征日 2026-05-15 ~ (最新交易日-40交易日)，
   有完整 40 日标签的最新区间（约 10~20 万样本，分钟级训练）
4. 树结构参数与旧模型一致（num_leaves=63, max_depth=8, min_data_in_leaf=100）——
   LightGBM continue training 要求结构一致；lr=0.02 略低保证平滑
5. 树上限 800（旧 500 + 增量 ≤800 = ≤1300 树），early stopping 100

验证：增量 vs 旧模型同批股票 Spearman 应 >0.95（平滑）；树数 ≤1300；增量 IC ≥ 旧模型。
"""
import sys, json, time, numpy as np
import lightgbm as lgb
from pathlib import Path
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.db import get_tushare_db

BASE = Path.home() / '.hermes' / 'stockdb'
MODEL_DIR = BASE / 'models'

FEAT_WIN = 180
FWD_DAYS = 40
DATA_START = '2024-08-01'    # 特征窗口 180 交易日回溯起点（特征日 2026-01 需 2025-07 前数据）
FEAT_START = '2026-01-01'    # 增量特征日起点（v2 2026-08-07：从 5/15 扩到 1/1 加近期回放——
                             # v1 只含 5/15-6/11 下跌窗口，新树被单一环境劫持（y均值-14%→预测整体下移）；
                             # 回放覆盖上涨/震荡/下跌多环境，避免增量学成"只会跌市"）

# 特征配置（与生产 scoring.py 一致：26 BASE + 3 因子）
BASE_KEEP_INDICES = [0,1,2,3,4,5,6,7,8,9,11,12,13,14,15,18,19,20,21,22,23,24,25,26,28,29]
FACTOR_FIELDS = ['kdj_k', 'cci', 'rsi_12']
N_FEATS = len(BASE_KEEP_INDICES) + len(FACTOR_FIELDS)

# 旧模型结构参数（增量新树必须一致）
OLD_MODEL = MODEL_DIR / 'lgb_reg_40d_new_stkfactor.txt'
OLD_STATS = MODEL_DIR / 'v6_norm_stats_40d_tushare_v2_stkfactor.json'
OUT_MODEL = MODEL_DIR / 'lgb_reg_40d_inc_v2.txt'


def preload_factors(conn, stocks, start_date):
    """预加载因子（extra JSON _bfq，与推理侧 get_factor_from_db 同口径）"""
    import json as _json
    print("  预加载因子数据（extra JSON _bfq）...", flush=True)
    ts_map = {}
    for s in stocks:
        tscode = f"{s}.SH" if s.startswith(('6','68','9')) else f"{s}.SZ"
        ts_map[tscode] = s
    tscodes = list(ts_map.keys())
    factor_data = {}
    batch_size = 500

    def _resolve(extra_dict, f):
        if not extra_dict:
            return None
        key = f + '_bfq'
        if key in extra_dict and extra_dict[key] is not None:
            return float(extra_dict[key])
        if f.startswith('rsi_') and f[4:].isdigit():
            key2 = f'rsi_bfq_{f[4:]}'
            if key2 in extra_dict and extra_dict[key2] is not None:
                return float(extra_dict[key2])
        for k, v in extra_dict.items():
            if f in k and '_bfq' in k and v is not None:
                return float(v)
        return None

    for bi in range(0, len(tscodes), batch_size):
        batch = tscodes[bi:bi+batch_size]
        ph = ','.join(['?' for _ in batch])
        rows = conn.execute(f"""
            SELECT ts_code, trade_date, extra FROM stk_factor
            WHERE ts_code IN ({ph}) AND trade_date >= ?
            ORDER BY ts_code, trade_date
        """, batch + [start_date.replace('-','')]).fetchall()
        for r in rows:
            tsc, dt, extra_raw = r
            code = ts_map.get(tsc)
            if not code:
                continue
            try:
                ed = _json.loads(extra_raw) if extra_raw else None
            except Exception:
                ed = None
            vals = {f: (_resolve(ed, f) if ed else None) for f in FACTOR_FIELDS}
            if any(v is not None for v in vals.values()):
                factor_data[(code, str(dt))] = {
                    f: (vals[f] if vals[f] is not None else 0.0) for f in FACTOR_FIELDS
                }
        if (bi+1) % 1000 == 0:
            print(f"    因子: {bi+1}/{len(tscodes)} ts_codes", flush=True)
    print(f"    已加载 {len(factor_data)} 条因子记录", flush=True)
    return factor_data


def main():
    t0 = time.time()
    print("=" * 60, flush=True)
    print("40d 增量训练 — 保留旧基础 + 吸收新数据", flush=True)
    print(f"旧模型: {OLD_MODEL.name} | 增量特征日 >= {FEAT_START}", flush=True)
    print("=" * 60, flush=True)

    conn = get_tushare_db()
    from feat_tushare import compute_features, get_board_index, apply_forward_adjust, load_index_data
    idx_data = load_index_data()

    stocks = [r[0] for r in conn.execute("""
        SELECT symbol FROM stock_basic
        WHERE market != '北交所'
        AND (name NOT LIKE '%ST%' OR name IS NULL)
        AND symbol NOT LIKE '8%' AND symbol NOT LIKE '4%'
    """).fetchall()]
    print(f"股票: {len(stocks)}", flush=True)

    # 交易日历 + 特征日上限（最新交易日 - 40 交易日，保证完整标签）
    tdays = [str(r[0]) for r in conn.execute(
        "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
    last_td = tdays[-1]
    feat_end = tdays[-FWD_DAYS - 1] if len(tdays) > FWD_DAYS else last_td
    print(f"交易日: {tdays[0]}~{last_td} | 增量特征日上限: {feat_end}", flush=True)
    if feat_end <= FEAT_START.replace('-', ''):
        print("增量窗口为空，退出"); return

    factor_data = preload_factors(conn, stocks, DATA_START)

    X_all, y_all = [], []
    t_start = time.time()
    for ci, code in enumerate(stocks):
        ts_code = f"{code}.SH" if code.startswith(('6','68','9')) else f"{code}.SZ"
        rows = conn.execute(f"""
            SELECT trade_date, close, open, high, low, COALESCE(pct_chg,0), vol, amount
            FROM daily WHERE ts_code='{ts_code}'
            AND trade_date >= '{DATA_START.replace('-','')}'
            ORDER BY trade_date
        """).fetchall()
        if len(rows) < FEAT_WIN + FWD_DAYS + 10:
            continue
        closes = [float(r[1]) for r in rows]
        highs_raw = [float(r[3]) for r in rows]
        lows_raw = [float(r[4]) for r in rows]
        pcts = [float(r[5])/100.0 for r in rows]
        volumes = [float(r[6]) for r in rows]
        dates_str = [str(r[0])[:10] for r in rows]

        adj_rows = conn.execute(
            "SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date",
            [ts_code]).fetchall()
        adj_closes, adj_highs, adj_lows = apply_forward_adjust(closes, highs_raw, lows_raw, adj_rows)

        board_idx = get_board_index(code)
        idx_info = idx_data.get(board_idx)

        for i in range(FEAT_WIN, len(rows) - FWD_DAYS):
            dt_clean = dates_str[i].replace('-', '')
            if not (FEAT_START.replace('-', '') <= dt_clean <= feat_end):
                continue  # 只取增量窗口内的特征日
            win_c = adj_closes[i-FEAT_WIN:i+1]
            win_h = adj_highs[i-FEAT_WIN:i+1]
            win_l = adj_lows[i-FEAT_WIN:i+1]
            win_v = volumes[i-FEAT_WIN:i+1]
            win_p = pcts[i-FEAT_WIN:i+1]

            idx_close_dict = None
            if idx_info and dates_str[i] in idx_info.get('dict', {}):
                idx_close_dict = {d: v for d, v in idx_info['dict'].items() if d <= dates_str[i]}

            val_dict = {'ep': 0.5, 'bp': 0.5, 'ln_cap': 22.0}
            val_row = conn.execute(
                "SELECT pe_ttm, pb, total_mv FROM daily_basic WHERE ts_code=? AND trade_date=?",
                [ts_code, dt_clean]).fetchone()
            if val_row and val_row[0]:
                if val_row[0] and float(val_row[0]) > 0: val_dict['ep'] = 1.0 / float(val_row[0])
                if val_row[1] and float(val_row[1]) > 0: val_dict['bp'] = 1.0 / float(val_row[1])
                if val_row[2] and float(val_row[2]) > 0: val_dict['ln_cap'] = np.log(float(val_row[2]))

            feat_38 = compute_features(win_c, win_h, win_l, win_v, win_p, idx_close_dict, val_dict)
            feat_selected = np.array([feat_38[j] for j in BASE_KEEP_INDICES], dtype=np.float64)
            fv = factor_data.get((code, str(dates_str[i])), {})
            factor_vals = [float(fv.get(f, 0.0)) for f in FACTOR_FIELDS]
            feat_29 = np.append(feat_selected, np.array(factor_vals, dtype=np.float64))

            ret = (adj_closes[i + FWD_DAYS] / adj_closes[i] - 1) * 100
            X_all.append(feat_29)
            y_all.append(ret)

        if (ci+1) % 200 == 0:
            print(f"  {ci+1}/{len(stocks)}, {len(X_all):,} 样本, {time.time()-t_start:.0f}s", flush=True)

    conn.close()
    X_raw = np.array(X_all, dtype=np.float64)
    y = np.array(y_all, dtype=np.float64)
    print(f"\n增量样本: {len(X_raw):,} | y均值: {np.mean(y):.3f}", flush=True)
    if len(X_raw) < 10000:
        print("样本不足，退出"); return

    # 用旧 stats 标准化（关键：保持与旧树同一特征空间）
    old_stats = json.load(open(str(OLD_STATS)))
    def normalize(X):
        Xn = X.copy()
        for j in range(N_FEATS):
            key = f'feat_{j}'
            if key in old_stats and old_stats[key]['std'] > 0:
                Xn[:, j] = np.clip(Xn[:, j], old_stats[key]['low'], old_stats[key]['high'])
                Xn[:, j] = (Xn[:, j] - old_stats[key]['mean']) / old_stats[key]['std']
        return np.nan_to_num(Xn, nan=0.0)

    n_train = int(len(X_raw) * 0.8)
    X_train_n = normalize(X_raw[:n_train])
    X_val_n = normalize(X_raw[n_train:])
    y_train, y_val = y[:n_train], y[n_train:]

    dtrain = lgb.Dataset(X_train_n, y_train)
    dval = lgb.Dataset(X_val_n, y_val, reference=dtrain)

    # 结构参数与旧模型一致（continue training 要求）；lr 更低保平滑（v2: 0.02→0.01）
    params = {
        'objective': 'regression', 'metric': 'l2',
        'num_leaves': 63, 'max_depth': 8, 'learning_rate': 0.01,
        'feature_fraction': 0.7, 'bagging_fraction': 0.8, 'bagging_freq': 5,
        'min_data_in_leaf': 100, 'verbose': 1, 'num_threads': 8,
    }
    print("\n增量训练中（init_model=旧模型，v2 低强度）...", flush=True)
    model = lgb.train(params, dtrain, num_boost_round=300,
        valid_sets=[dtrain, dval], valid_names=['train','val'],
        init_model=lgb.Booster(model_file=str(OLD_MODEL)),
        callbacks=[lgb.early_stopping(100), lgb.log_evaluation(50)])

    pred_val = model.predict(X_val_n)
    ic_val = stats.spearmanr(pred_val, y_val)[0]

    # 旧模型在同样本上的 IC（对照）
    old_m = lgb.Booster(model_file=str(OLD_MODEL))
    ic_old = stats.spearmanr(old_m.predict(X_val_n), y_val)[0]

    print(f"\n总树数: {model.num_trees()} (旧{old_m.num_trees()} + 增量{model.num_trees()-old_m.num_trees()})", flush=True)
    print(f"增量验证集 IC: {ic_val:.4f} vs 旧模型同集 IC: {ic_old:.4f}", flush=True)

    model.save_model(str(OUT_MODEL))
    print(f"已保存: {OUT_MODEL}", flush=True)
    print(f"耗时: {(time.time()-t0)/60:.1f} min", flush=True)


if __name__ == '__main__':
    main()
