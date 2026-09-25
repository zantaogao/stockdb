"""
10d Mac v1 — feat_tushare管道，31维纯量价，PV_INDICES
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

FEAT_WIN = 60
FWD_DAYS = 10

# 31维纯量价特征 (PV_INDICES)
PV_INDICES = [
    0,1,2,3,    5,6,7,    10,11,
    12,13,14,15,16,17,  18,19,
    23,24,25,  26,27,  28,29,  30,
    32,33,34,35,  36,37,
]
N_FEATS = len(PV_INDICES)

FEAT_NAMES = [
    'chg5','chg10','chg20','chg60',  # 0-3: 涨幅
    'd5','d10','d20',                 # 5-7: 动量差
    'rr','std20',                     # 10-11: 风险
    'vr','pos','c1d','c3d',           # 12-15: 量能
    'ep','bp','ln_cap',               # 16-18: 估值
    'ex5','ex10','ex20',              # 23-25: 超额
    'skew20','dn_streak',             # 26-27: 形态
    'up_ratio10',                     # 28: 上涨比例
    'bull2','chg120','d120',          # 29-30: 长周期
    'chg5_20','chg10_20','ret_ms',    # 32-34: 相对
    'vol5','vol10','maxret5','dn_vol',# 35-38
]

def main():
    t0 = time.time()
    print("="*60, flush=True)
    print("10d Mac v1 — feat_tushare 31维纯量价 | PV_INDICES", flush=True)
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
            feat = np.array([feat_38[j] for j in PV_INDICES], dtype=np.float64)
            
            fwd_close = adj_closes[i + FWD_DAYS] if i + FWD_DAYS < len(adj_closes) else adj_closes[-1]
            ret = (fwd_close / adj_closes[i] - 1) * 100
            
            X_all.append(feat)
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
    
    # 10d: 短期信号，轻量参数
    params = {
        'objective': 'regression', 'metric': 'l2',
        'num_leaves': 15, 'learning_rate': 0.01,
        'feature_fraction': 0.6, 'bagging_fraction': 0.7, 'bagging_freq': 5,
        'min_data_in_leaf': 300, 'lambda_l1': 0.5, 'lambda_l2': 2.0,
        'max_depth': 5, 'verbose': 1, 'num_threads': 8,
    }
    
    print("\n训练中...", flush=True)
    model = lgb.train(params, dtrain, num_boost_round=3000,
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
    
    model_path = MODEL_DIR / 'lgb_reg_10d_mac_v1.txt'
    stats_path = MODEL_DIR / 'v10_mac_v1_stats.json'
    model.save_model(str(model_path))
    with open(stats_path, 'w') as f:
        json.dump(stats_dict, f)
    
    elapsed = time.time() - t0
    print(f"\n已保存: {model_path}", flush=True)
    print(f"树数: {model.num_trees()}", flush=True)
    print(f"耗时: {elapsed:.0f}s ({elapsed/60:.1f}min)", flush=True)

if __name__ == '__main__':
    main()
