"""
40d Mac v1 — feat_tushare管道，29维(26BASE+3因子)，预加载因子
"""
import sys, json, time, numpy as np
import lightgbm as lgb
from pathlib import Path
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.db import get_tushare_db
from feat_tushare import compute_features, get_board_index, apply_forward_adjust, load_index_data

BASE = Path.home() / '.hermes' / 'stockdb'
MODEL_DIR = BASE / 'models'

FEAT_WIN = 180     # 长窗口
FWD_DAYS = 40      # 40日预测

BASE_KEEP_INDICES = [0,1,2,3,4,5,6,7,8,9,11,12,13,14,15,18,19,20,21,22,23,24,25,26,28,29]
FACTOR_FIELDS = ['kdj_k', 'cci', 'rsi_12']
N_FEATS = len(BASE_KEEP_INDICES) + len(FACTOR_FIELDS)

FEAT_NAMES = [
    'chg5','chg10','chg20','chg60','chg120',
    'd5','d10','d20','d60','d120',
    'bull2','rr','std20','vr','pos',
    'c1d','c3d','ep','bp','ln_cap',
    'ex5','ex10','ex20','skew20','dn_streak','up_ratio10',
    'kdj_k','cci','rsi_12',
]

def preload_factors(conn, stocks, start_date='2022-01-01'):
    """预加载因子数据（2026-08-07 修复：原读 stk_factor 直接列 kdj_k/cci/rsi_12 全 0——
    真实因子在 extra JSON _bfq 键，与推理侧 get_factor_from_db 同口径）"""
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
        """与 feat_tushare.get_factor_from_db._resolve 同规则：
        1) 精确 f+'_bfq' 2) rsi_bfq_<N> 3) 模糊含 f 且含 _bfq"""
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
        placeholders = ','.join(['?' for _ in batch])
        rows = conn.execute(f"""
            SELECT ts_code, trade_date, extra FROM stk_factor
            WHERE ts_code IN ({placeholders}) AND trade_date >= ?
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
            # 只存有非 None 值的记录（缺省=0.0，与原行为等价但省内存）
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
    print("="*60, flush=True)
    print("40d Mac v1 — feat_tushare 29维(26BASE+3因子) | 预加载因子", flush=True)
    print(f"窗口={FEAT_WIN}天 | 分割=时间序80%", flush=True)
    print("="*60, flush=True)
    
    conn = get_tushare_db()
    idx_data = load_index_data()
    
    stocks = [r[0] for r in conn.execute("""
        SELECT symbol FROM stock_basic 
        WHERE market != '北交所' 
        AND (name NOT LIKE '%ST%' OR name IS NULL)
        AND symbol NOT LIKE '8%' AND symbol NOT LIKE '4%'
    """).fetchall()]
    print(f"股票: {len(stocks)}", flush=True)
    
    factor_data = preload_factors(conn, stocks)
    
    X_all, y_all = [], []
    t_start = time.time()
    for ci, code in enumerate(stocks):
        ts_code = f"{code}.SH" if code.startswith(('6','68','9')) else f"{code}.SZ"
        
        rows = conn.execute(f"""
            SELECT trade_date, close, open, high, low, COALESCE(pct_chg,0), vol, amount
            FROM daily WHERE ts_code='{ts_code}'
            AND trade_date >= '2022-01-01'
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
            [ts_code]
        ).fetchall()
        adj_closes, adj_highs, adj_lows = apply_forward_adjust(closes, highs_raw, lows_raw, adj_rows)
        
        board_idx = get_board_index(code)
        idx_info = idx_data.get(board_idx)
        
        for i in range(FEAT_WIN, len(rows) - FWD_DAYS):
            win_c = adj_closes[i-FEAT_WIN:i+1]
            win_h = adj_highs[i-FEAT_WIN:i+1]
            win_l = adj_lows[i-FEAT_WIN:i+1]
            win_v = volumes[i-FEAT_WIN:i+1]
            win_p = pcts[i-FEAT_WIN:i+1]
            
            dt_clean = dates_str[i].replace('-', '')
            
            idx_close_dict = None
            if idx_info and dates_str[i] in idx_info.get('dict', {}):
                idx_close_dict = {d: v for d, v in idx_info['dict'].items() if d <= dates_str[i]}
            
            val_dict = {'ep': 0.5, 'bp': 0.5, 'ln_cap': 22.0}
            val_row = conn.execute(
                "SELECT pe_ttm, pb, total_mv FROM daily_basic WHERE ts_code=? AND trade_date=?",
                [ts_code, dt_clean]
            ).fetchone()
            if val_row and val_row[0]:
                if val_row[0] and float(val_row[0]) > 0: val_dict['ep'] = 1.0 / float(val_row[0])
                if val_row[1] and float(val_row[1]) > 0: val_dict['bp'] = 1.0 / float(val_row[1])
                if val_row[2] and float(val_row[2]) > 0: val_dict['ln_cap'] = np.log(float(val_row[2]))
            
            feat_38 = compute_features(win_c, win_h, win_l, win_v, win_p, idx_close_dict, val_dict)
            feat_selected = np.array([feat_38[j] for j in BASE_KEEP_INDICES], dtype=np.float64)
            
            fv = factor_data.get((code, str(dates_str[i])), {})
            factor_vals = [float(fv.get(f, 0.0)) for f in FACTOR_FIELDS]
            feat_29 = np.append(feat_selected, np.array(factor_vals, dtype=np.float64))
            
            fwd_close = adj_closes[i + FWD_DAYS] if i + FWD_DAYS < len(adj_closes) else adj_closes[-1]
            ret = (fwd_close / adj_closes[i] - 1) * 100
            
            X_all.append(feat_29)
            y_all.append(ret)
        
        if (ci+1) % 200 == 0:
            elapsed = time.time() - t_start
            print(f"  {ci+1}/{len(stocks)}, {len(X_all):,} 样本, {elapsed:.0f}s", flush=True)
    
    conn.close()
    
    X_raw = np.array(X_all, dtype=np.float64)
    y = np.array(y_all, dtype=np.float64)
    print(f"\n总样本: {len(X_raw):,}", flush=True)
    print(f"y范围: {y.min():.2f}~{y.max():.2f}, 均值:{np.mean(y):.4f}, std:{np.std(y):.4f}", flush=True)
    
    if len(X_raw) < 50000:
        print(f"样本不足: {len(X_raw)}", flush=True)
        return
    
    n_train = int(len(X_raw) * 0.8)
    X_train, y_train = X_raw[:n_train], y[:n_train]
    X_val, y_val = X_raw[n_train:], y[n_train:]
    
    stats_dict = {}
    for j in range(N_FEATS):
        vals = X_raw[:, j]
        valid = vals[~np.isnan(vals) & ~np.isinf(vals)]
        if len(valid) > 0:
            stats_dict[f'feat_{j}'] = {
                'mean': float(np.mean(valid)), 'std': float(np.std(valid)),
                'low': float(np.percentile(valid, 1)), 'high': float(np.percentile(valid, 99)),
            }
    
    def normalize(X, s):
        Xn = X.copy()
        for j in range(N_FEATS):
            key = f'feat_{j}'
            if key in s and s[key]['std'] > 0:
                Xn[:, j] = np.clip(Xn[:, j], s[key]['low'], s[key]['high'])
                Xn[:, j] = (Xn[:, j] - s[key]['mean']) / s[key]['std']
        return np.nan_to_num(Xn, nan=0.0)
    
    X_train_n = normalize(X_train, stats_dict)
    X_val_n = normalize(X_val, stats_dict)
    
    dtrain = lgb.Dataset(X_train_n, y_train)
    dval = lgb.Dataset(X_val_n, y_val, reference=dtrain)
    
    params = {
        'objective': 'regression', 'metric': 'l2',
        'num_leaves': 31, 'learning_rate': 0.03,  # 2026-08-07 v3: lr 0.01→0.03（与旧模型同量级，v2 的 0.01 导致 5000 树未收敛）
        'feature_fraction': 0.7, 'bagging_fraction': 0.7, 'bagging_freq': 5,
        'min_data_in_leaf': 200, 'lambda_l1': 0.1, 'lambda_l2': 1.0,
        'max_depth': 6, 'verbose': 1, 'num_threads': 8,
    }
    
    print("\n训练中...", flush=True)
    model = lgb.train(params, dtrain, num_boost_round=3000,  # v3: 上限 5000→3000（lr 提高后 early stopping 应提前触发）
        valid_sets=[dtrain, dval], valid_names=['train','val'],
        callbacks=[lgb.early_stopping(100), lgb.log_evaluation(200)])
    
    pred_train = model.predict(X_train_n)
    pred_val = model.predict(X_val_n)
    ic_train = stats.spearmanr(pred_train, y_train)[0]
    ic_val = stats.spearmanr(pred_val, y_val)[0]
    
    val_pairs = sorted(zip(pred_val, y_val), key=lambda x: x[0])
    d10 = max(1, len(val_pairs)//10)
    print(f"\n{'='*60}", flush=True)
    print("验证集十分组:", flush=True)
    for d in range(10):
        s,e = d*d10, (d+1)*d10 if d<9 else len(val_pairs)
        rets = [r for _,r in val_pairs[s:e]]
        print(f"  D{d+1}: {np.mean(rets):+.2f}%", flush=True)
    spread = np.mean([r for _,r in val_pairs[-d10:]]) - np.mean([r for _,r in val_pairs[:d10]])
    print(f"  Spread: {spread:+.2f}%", flush=True)
    print(f"  Train IC: {ic_train:.4f}", flush=True)
    print(f"  Val IC:   {ic_val:.4f}", flush=True)
    
    # 2026-08-07: 输出 v3 新文件（v2=5000树未收敛版保留对照；生产 lgb_reg_40d_new_stkfactor.txt 不动）
    model_path = MODEL_DIR / 'lgb_reg_40d_mac_v3.txt'
    stats_path = MODEL_DIR / 'v40_mac_v3_stats.json'
    model.save_model(str(model_path))
    with open(stats_path, 'w') as f:
        json.dump(stats_dict, f)
    
    elapsed = time.time() - t0
    print(f"\n已保存: {model_path}", flush=True)
    print(f"树数: {model.num_trees()}", flush=True)
    print(f"耗时: {elapsed:.0f}s ({elapsed/60:.1f}min)", flush=True)

if __name__ == '__main__':
    main()
