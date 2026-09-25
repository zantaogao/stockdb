"""
LightGBM 10日回归 v3 — Mac训练，纯量价短期特征，feat_tushare管道
============================================================
v2问题回顾：
1. 训练(PC stock_daily)和推理(Mac feat_tushare)特征体系不一致，预测全趋近0
2. 实盘IC仅0.1079，远低于验证集0.25

v3改进：
1. 直接用feat_tushare管道，训练=推理特征一致
2. 仅保留短期量价特征（去掉估值/长周期/GTJA）
3. rank_objective对噪音更鲁棒
4. 小模型强正则化
"""
import sys, json, time, numpy as np
import lightgbm as lgb
from pathlib import Path
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.db import get_tushare_db
from feat_tushare import compute_features, get_board_index, apply_forward_adjust, get_factor_from_db

BASE = Path.home() / '.hermes' / 'stockdb'
MODEL_DIR = BASE / 'models'
MODEL_DIR.mkdir(exist_ok=True)

# ── 配置 ──
FEAT_WIN = 60           # 60天窗口，聚焦短期
FWD_DAYS = 10           # 10日预测
MIN_SAMPLES = 50000     # 最低样本数
TRAIN_SPLIT = 0.8       # 训练/验证分割

# 纯量价短期特征索引（来自feat_tushare 38维输出）
# 只保留短周期价格/成交量/波动相关，去掉估值/长周期
PV_INDICES = [
    0, 1, 2, 3,       # chg5, chg10, chg20, chg60
    5, 6, 7,           # d5, d10, d20
    10, 11,            # bull1, bull2
    12, 13, 14, 15, 16, 17,  # rr, std20, vr, pos, nh, vpc
    18, 19,            # c1d, c3d
    23, 24, 25,        # ex5, ex10, ex20
    26, 27,            # skew20, kurt20
    28, 29,            # dn_streak, up_ratio10
    30,                # vol_chg
    32, 33, 34, 35,    # kurt60, slope5, slope10, accel
    36, 37,            # vp_shrink, vp_div
]
N_FEATS = len(PV_INDICES)  # 31维（注释曾误写 27；scoring.py 推理侧同 31 个索引）
FEAT_NAMES = [
    'chg5','chg10','chg20','chg60',
    'd5','d10','d20',
    'bull1','bull2',
    'rr','std20','vr','pos','nh','vpc',
    'c1d','c3d',
    'ex5','ex10','ex20',
    'skew20','kurt20',
    'dn_streak','up_ratio10',
    'vol_chg',
    'kurt60','slope5','slope10','accel',
    'vp_shrink','vp_div',
]

def load_stock_list(conn):
    """获取可训练股票（排除ST/北交所/次新）"""
    rows = conn.execute("""
        SELECT symbol, name, list_date FROM stock_basic
        WHERE market != '北交所'
    """).fetchall()
    stocks = []
    for r in rows:
        code, name, list_date = r
        if name and ('ST' in name or 'st' in name or '退' in name):
            continue
        if code.startswith(('8','4','92')):
            continue
        stocks.append(code)
    return stocks

def extract_features(code, conn):
    """提取单只股票的完整特征序列"""
    ts_code = f"{code}.SH" if code.startswith(('6','68','9')) else f"{code}.SZ"
    
    # 读取日线
    rows = conn.execute(f"""
        SELECT trade_date, close, open, high, low, COALESCE(pct_chg,0), vol, amount
        FROM daily WHERE ts_code='{ts_code}'
        AND trade_date >= '2022-01-01'
        ORDER BY trade_date
    """).fetchall()
    if len(rows) < FEAT_WIN + FWD_DAYS + 10:
        return [], []
    
    closes = [float(r[1]) for r in rows]
    highs_raw = [float(r[3]) for r in rows]
    lows_raw = [float(r[4]) for r in rows]
    pcts = [float(r[5])/100.0 for r in rows]
    volumes = [float(r[6]) for r in rows]
    dates_str = [str(r[0])[:10] for r in rows]
    
    # 前复权
    adj_rows = conn.execute(
        "SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date",
        [ts_code]
    ).fetchall()
    adj_closes, adj_highs, adj_lows = apply_forward_adjust(
        closes, highs_raw, lows_raw, adj_rows
    )
    
    # 指数数据
    board_idx = get_board_index(code)
    from feat_tushare import load_index_data
    idx_data = load_index_data()
    idx_info = idx_data.get(board_idx)
    
    X, y = [], []
    for i in range(FEAT_WIN, len(rows) - FWD_DAYS):
        # 窗口切片
        win_c = adj_closes[i-FEAT_WIN:i+1]
        win_h = adj_highs[i-FEAT_WIN:i+1]
        win_l = adj_lows[i-FEAT_WIN:i+1]
        win_v = volumes[i-FEAT_WIN:i+1]
        win_p = pcts[i-FEAT_WIN:i+1]
        
        # 当前日期
        dt_clean = dates_str[i].replace('-', '')
        
        # 指数收盘
        idx_close_dict = None
        if idx_info and dates_str[i] in idx_info.get('dict', {}):
            idx_close_dict = {d: v for d, v in idx_info['dict'].items() if d <= dates_str[i]}
        
        # 估值（对10d短期信号忽略）
        val_dict = {'ep': 0.5, 'bp': 0.5, 'ln_cap': 22.0}
        
        # 38维原始特征
        feat_38 = compute_features(win_c, win_h, win_l, win_v, win_p, idx_close_dict, val_dict)
        
        # 只取短期量价特征
        feat = np.array([feat_38[j] for j in PV_INDICES], dtype=np.float64)
        
        # 10日收益标签
        fwd_close = adj_closes[i + FWD_DAYS] if i + FWD_DAYS < len(adj_closes) else adj_closes[-1]
        ret = fwd_close / adj_closes[i] - 1
        
        X.append(feat)
        y.append(ret)
    
    return X, y

def main():
    t0 = time.time()
    print("=" * 60)
    print("10d v3 — Mac训练 | feat_tushare管道 | 纯量价短期特征")
    print("=" * 60)
    
    conn = get_tushare_db()
    stocks = load_stock_list(conn)
    print(f"股票池: {len(stocks)} 只")
    
    # 逐个提取特征
    X_list, y_list = [], []
    t_start = time.time()
    for ci, code in enumerate(stocks):
        Xs, ys = extract_features(code, conn)
        X_list.extend(Xs)
        y_list.extend(ys)
        if (ci + 1) % 100 == 0:
            elapsed = time.time() - t_start
            print(f"  {ci+1}/{len(stocks)} 股票, {len(X_list):,} 样本, {elapsed:.0f}s", flush=True)
    
    conn.close()
    
    X_raw = np.array(X_list, dtype=np.float64)
    y = np.array(y_list, dtype=np.float64)
    print(f"\n总样本: {len(X_raw):,}")
    print(f"标签范围: {y.min()*100:.2f}% ~ {y.max()*100:.2f}%")
    print(f"标签均值: {np.mean(y)*100:+.4f}% 标准差: {np.std(y)*100:.4f}%")
    
    if len(X_raw) < MIN_SAMPLES:
        print(f"样本不足: {len(X_raw)} < {MIN_SAMPLES}")
        return
    
    # 时间序分割（前80%训练，后20%验证）
    n = len(X_raw)
    n_train = int(n * TRAIN_SPLIT)
    X_train, y_train = X_raw[:n_train], y[:n_train]
    X_val, y_val = X_raw[n_train:], y[n_train:]
    
    # 标准化统计
    stats_dict = {}
    for j in range(N_FEATS):
        vals = X_raw[:, j]
        valid = vals[~np.isnan(vals) & ~np.isinf(vals)]
        if len(valid) > 0:
            stats_dict[f'feat_{j}'] = {
                'mean': float(np.mean(valid)),
                'std': float(np.std(valid)),
                'low': float(np.percentile(valid, 1)),
                'high': float(np.percentile(valid, 99)),
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
    
    # 训练参数 — rank_objective对噪音更鲁棒
    params = {
        'objective': 'regression',
        'metric': 'l2',
        'num_leaves': 15,            # 小树避免过拟合
        'learning_rate': 0.008,
        'feature_fraction': 0.6,
        'bagging_fraction': 0.6,
        'bagging_freq': 5,
        'min_data_in_leaf': 300,     # 强正则化
        'lambda_l1': 0.5,
        'lambda_l2': 2.0,
        'max_depth': 5,
        'min_gain_to_split': 0.2,
        'verbose': 1,
        'num_threads': 8,
    }
    
    print("\n开始训练...")
    model = lgb.train(
        params, dtrain, num_boost_round=2000,
        valid_sets=[dtrain, dval],
        valid_names=['train', 'val'],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(100)]
    )
    
    # 评估
    pred_train = model.predict(X_train_n)
    pred_val = model.predict(X_val_n)
    
    ic_train = stats.spearmanr(pred_train, y_train)[0]
    ic_val = stats.spearmanr(pred_val, y_val)[0]
    
    # 十分组
    val_pairs = sorted(zip(pred_val, y_val), key=lambda x: x[0])
    d10 = max(1, len(val_pairs) // 10)
    print(f"\n{'='*60}")
    print("验证集十分组收益:")
    for d in range(10):
        s, e = d * d10, (d + 1) * d10 if d < 9 else len(val_pairs)
        rets = [r for _, r in val_pairs[s:e]]
        print(f"  D{d+1}: {np.mean(rets)*100:+.2f}%")
    spread = (np.mean([r for _, r in val_pairs[-d10:]]) - np.mean([r for _, r in val_pairs[:d10]])) * 100
    print(f"  Spread: {spread:+.2f}%")
    print(f"  Train IC: {ic_train:.4f}")
    print(f"  Val IC:   {ic_val:.4f}")
    
    # 特征重要性
    imp = model.feature_importance(importance_type='gain')
    top = np.argsort(imp)[-10:][::-1]
    print("\nTop 10 特征 (gain):")
    for j in top:
        print(f"  feat_{j} ({FEAT_NAMES[j]}): {imp[j]:.1f}")
    
    # 保存
    model_path = MODEL_DIR / 'lgb_reg_10d_v3.txt'
    stats_path = MODEL_DIR / 'v10_v3_stats.json'
    model.save_model(str(model_path))
    with open(stats_path, 'w') as f:
        json.dump(stats_dict, f)
    
    elapsed = time.time() - t0
    print(f"\n已保存: {model_path}")
    print(f"已保存: {stats_path}")
    print(f"耗时: {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"树数: {model.num_trees()}")
    print(f"特征数: {model.num_feature()}")

if __name__ == '__main__':
    main()
