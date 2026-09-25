#!/usr/bin/env python3
"""20d 回归重训 v7 — PC 版 (tushare.db 独立，无 state.db)"""
import json, os, sys, time, math
import numpy as np
import lightgbm as lgb
from pathlib import Path
from scipy.stats import spearmanr, skew, kurtosis
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).parent.parent))
import duckdb

# PC 环境配置（Windows）
import platform
if platform.system() == 'Windows':
    BASE = Path('C:/Users/pumma.zantao')
else:
    BASE = Path.home() / 'pumma'
DB_PATH = BASE / 'tushare.db'
MODEL_DIR = BASE / 'models'
SPLIT_TRAIN = '2025-01-01'
SPLIT_VAL = '2026-01-01'
FWD_DAYS = 20
MAX_LABEL = 50.0
N_FEATS = 49  # 38 基础 + 11 tushare 因子
WINDOW = 120

def load_valmap(conn):
    """从 tushare.db 读取估值数据"""
    vm = conn.execute("""
        SELECT stock_code, date, pe_ttm, pb, total_mv
        FROM stock_valuation ORDER BY stock_code, date
    """).fetchall()
    r = {}
    for code, dt, pe, pb, mv in vm:
        e = {}
        if pe and float(pe) > 0: e['ep'] = 1.0 / float(pe)
        if pb and float(pb) > 0: e['bp'] = 1.0 / float(pb)
        if mv and float(mv) > 0: e['ln_cap'] = np.log(float(mv))
        if e: r[(code, str(dt)[:10])] = e
    return r

def load_index_close(conn):
    """从 tushare.db 读取指数收盘价"""
    rows = conn.execute("""
        SELECT trade_date, close 
        FROM index_daily_raw 
        WHERE ts_code = '000001.SH' 
        ORDER BY trade_date
    """).fetchall()
    return {str(r[0])[:10]: float(r[1]) for r in rows}

def main():
    t0 = time.time()
    print("=" * 65, flush=True)
    print(f"20d 回归重训 v7 (PC 版) — {WINDOW}天窗口，{N_FEATS}维", flush=True)
    print(f"  数据源：{DB_PATH}", flush=True)
    print(f"  切分：{SPLIT_TRAIN}/{SPLIT_VAL}", flush=True)
    print("=" * 65, flush=True)

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    
    # 读取股票列表（从 stock_info）
    # 测试模式：只跑前 1000 只股票（确认逻辑正确）
    all_stocks = [r[0] for r in conn.execute("""
        SELECT stock_code FROM stock_info
        WHERE stock_code NOT LIKE '8%' AND stock_code NOT LIKE '4%'
        AND market != '北交所' AND (stock_name NOT LIKE '%ST%' OR stock_name IS NULL)
        ORDER BY stock_code
        LIMIT 1000  -- 测试模式：先跑 1000 只
    """).fetchall()]
    stocks = all_stocks
    print(f"\n股票：{len(stocks)} (测试模式：前 1000 只)", flush=True)

    vm = load_valmap(conn)
    print(f"估值：{len(vm)} 条", flush=True)

    idx_close = load_index_close(conn)
    print(f"指数：{len(idx_close)} 个交易日", flush=True)

    # SQL 窗口函数计算基础特征
    print("\nSQL SQL 特征...", flush=True)
    conn.execute(f"""
        CREATE TEMP TABLE feats AS
        SELECT s.stock_code as stock_code, s.date as date,
            (s.close / LAG(s.close, 5) OVER w - 1) chg5,
            (s.close / LAG(s.close, 10) OVER w - 1) chg10,
            (s.close / LAG(s.close, 20) OVER w - 1) chg20,
            (s.close / LAG(s.close, 60) OVER w - 1) chg60,
            (s.close / LAG(s.close, 120) OVER w - 1) chg120,
            (s.close / AVG(s.close) OVER(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) - 1) d5,
            (s.close / AVG(s.close) OVER(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) - 1) d10,
            (s.close / AVG(s.close) OVER(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) - 1) d20,
            (s.close / AVG(s.close) OVER(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) - 1) d60,
            (s.close / AVG(s.close) OVER(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW) - 1) d120,
            (LEAD(s.close, {FWD_DAYS}) OVER w / s.close - 1) * 100 "label",
            COALESCE(s.change_pct, 0) / 100 c1d,
            (s.close / LAG(s.close, 3) OVER w - 1) c3d
        FROM stock_daily s
        WINDOW w AS (PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN {WINDOW - 1} PRECEDING AND CURRENT ROW)
    """)
    conn.execute("""
        CREATE TEMP TABLE feats2 AS
        SELECT f.*,
            CASE WHEN d5 > d10 AND d10 > d20 THEN 1 ELSE 0 END bull1,
            CASE WHEN d20 > d60 THEN 1 ELSE 0 END bull2
        FROM feats f
    """)
    conn.execute('DELETE FROM feats2 WHERE chg60 IS NULL OR "label" IS NULL')
    conn.execute(f'DELETE FROM feats2 WHERE ABS("label") > {MAX_LABEL}')
    n_v = conn.execute("SELECT COUNT(*) FROM feats2").fetchone()[0]
    print(f"  有效：{n_v:,}", flush=True)

    # 导出基础特征
    arr = conn.execute("""
        SELECT stock_code, date, chg5, chg10, chg20, chg60, chg120,
               d5, d10, d20, d60, d120, bull1, bull2, c1d, c3d, "label"
        FROM feats2 ORDER BY stock_code, date
    """).fetchall()
    codes = [r[0] for r in arr]
    dates = [str(r[1])[:10] for r in arr]
    raw = np.array([list(r[2:]) for r in arr], dtype=np.float64)
    y = raw[:, -1].copy()
    raw = raw[:, :-1]
    print(f"  原始特征：{raw.shape}  y: {y.shape}", flush=True)

    # 重建 38 维 F_base
    n = len(codes)
    F = np.zeros((n, 38), dtype=np.float64)
    F[:, 0] = raw[:, 0]   # chg5
    F[:, 1] = raw[:, 1]   # chg10
    F[:, 2] = raw[:, 2]   # chg20
    F[:, 3] = raw[:, 3]   # chg60
    F[:, 4] = raw[:, 4]   # chg120
    F[:, 5] = raw[:, 5]   # d5
    F[:, 6] = raw[:, 6]   # d10
    F[:, 7] = raw[:, 7]   # d20
    F[:, 8] = raw[:, 8]   # d60
    F[:, 9] = raw[:, 9]   # d120
    F[:, 10] = raw[:, 10] # bull1
    F[:, 11] = raw[:, 11] # bull2
    F[:, 18] = raw[:, 12] # c1d
    F[:, 19] = raw[:, 13] # c3d
    print(f"  38 维 F_base 初始化完成", flush=True)

    # 补充超额收益
    print("\nEx 超额收益计算...", flush=True)
    idt_sorted = sorted(idx_close.keys())
    dt_to_pos = {d: i for i, d in enumerate(idt_sorted)}
    n_idx = len(idt_sorted)
    idx_cl = np.array([idx_close[d] for d in idt_sorted], dtype=np.float64)
    
    idx_ret_5 = np.full(n_idx, np.nan)
    idx_ret_10 = np.full(n_idx, np.nan)
    idx_ret_20 = np.full(n_idx, np.nan)
    for i in range(5, n_idx):
        idx_ret_5[i] = idx_cl[i] / idx_cl[i-5] - 1
    for i in range(10, n_idx):
        idx_ret_10[i] = idx_cl[i] / idx_cl[i-10] - 1
    for i in range(20, n_idx):
        idx_ret_20[i] = idx_cl[i] / idx_cl[i-20] - 1
    
    ex5_arr, ex10_arr, ex20_arr = np.zeros(n), np.zeros(n), np.zeros(n)
    for i in range(n):
        dt = dates[i]
        pos = dt_to_pos.get(dt)
        if pos is not None:
            ex5_arr[i] = F[i, 0] - (idx_ret_5[pos] if not np.isnan(idx_ret_5[pos]) else 0)
            ex10_arr[i] = F[i, 1] - (idx_ret_10[pos] if not np.isnan(idx_ret_10[pos]) else 0)
            ex20_arr[i] = F[i, 2] - (idx_ret_20[pos] if not np.isnan(idx_ret_20[pos]) else 0)
    
    F[:, 23] = ex5_arr
    F[:, 24] = ex10_arr
    F[:, 25] = ex20_arr
    print(f"  超额收益已填充: ex5={np.nanmean(ex5_arr):.4f} ex10={np.nanmean(ex10_arr):.4f} ex20={np.nanmean(ex20_arr):.4f}", flush=True)

    # 加载 tushare 原始因子（动态获取列名）
    print("\nF 加载 tushare 原始因子...", flush=True)
    
    # 先检查 stk_factor 表的列名
    cols = conn.execute("DESCRIBE stk_factor").fetchall()
    col_names = [c[0] for c in cols]
    print(f"  stk_factor 列名: {col_names[:10]}...", flush=True)
    
    # 找出我们需要的因子列（模糊匹配）
    needed_factors = ['rsi', 'momentum', 'amount', 'vol', 'pct', 'change', 'reversal', 'std', 'bb', 'roc', 'cci']
    available_factors = []
    for needed in needed_factors:
        for col in col_names:
            if needed.lower() in col.lower():
                available_factors.append(col)
                print(f"    找到因子: {col}", flush=True)
                break
    
    if len(available_factors) == 0:
        print("  [warn] 无匹配因子，用 0 填充", flush=True)
        factor_df = conn.execute("SELECT ts_code, trade_date FROM stk_factor LIMIT 0").fetchdf()
    else:
        # 限制最多 11 个因子
        factor_cols_str = ', '.join(available_factors[:11])
        factor_query = f"""
            SELECT ts_code, trade_date, {factor_cols_str}
            FROM stk_factor 
            WHERE trade_date >= '20240101' 
            ORDER BY ts_code, trade_date
        """
        print(f"  查询因子: {factor_cols_str}", flush=True)
        factor_df = conn.execute(factor_query).fetchdf()
    
    factor_df['trade_date'] = factor_df['trade_date'].astype(str)
    
    if len(factor_df) > 0:
        print(f"  tushare 因子数据：{len(factor_df)} 条", flush=True)
        factor_df = factor_df.fillna(0)
        
        factor_cols = [c for c in factor_df.columns if c not in ['ts_code', 'trade_date']]
        valid_factors = []
        for col in factor_cols:
            non_zero = (factor_df[col] != 0).sum()
            if non_zero > 0:
                valid_factors.append(col)
                print(f"    {col}: {non_zero} 非零值", flush=True)
            else:
                print(f"    [warn] {col}: 全 0，跳过", flush=True)
        
        tushare_factors = factor_df[valid_factors[:11]].values if valid_factors else np.zeros((len(factor_df), 1))
        print(f"  有效因子：{len(valid_factors[:11])} 维", flush=True)
    else:
        tushare_factors = np.zeros((1, 1))
        print("  [warn] 无 tushare 因子数据，用 0 填充", flush=True)

    # 对齐因子到数据索引
    code_date_to_idx = {(codes[i], dates[i]): i for i in range(n)}
    gtja_cols = np.zeros((n, 11), dtype=np.float64)
    
    if len(factor_df) > 0 and tushare_factors.shape[0] > 0:
        factor_idx_map = {}
        for i, row in factor_df.iterrows():
            key = (row['ts_code'], row['trade_date'])
            if key in code_date_to_idx:
                factor_idx_map[code_date_to_idx[key]] = i
        
        for idx, factor_i in factor_idx_map.items():
            if factor_i < tushare_factors.shape[0]:
                gtja_cols[idx, :tushare_factors.shape[1]] = tushare_factors[factor_i]
        
        print(f"  因子对齐完成：{len(factor_idx_map)} 条匹配", flush=True)
    else:
        print("  [warn] 无有效因子数据，gtja_cols 全 0", flush=True)

    # 合并特征
    X = np.column_stack([F, gtja_cols])[:, :N_FEATS]
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    print(f"\n  X: {X.shape}", flush=True)

    # 检查全 0 列
    for j in range(N_FEATS):
        col = X[:, j]
        nonzero = np.count_nonzero(col)
        if nonzero < 100:
            print(f"  [warn] 列{j}: {nonzero}/{len(X)} 个非零", flush=True)

    # 切分
    Da = np.array(dates)
    m_tr = Da < SPLIT_TRAIN
    m_va = (Da >= SPLIT_TRAIN) & (Da < SPLIT_VAL)
    m_te = Da >= SPLIT_VAL

    X_tr, y_tr = X[m_tr], y[m_tr]
    X_va, y_va = X[m_va], y[m_va]
    X_te, y_te = X[m_te], y[m_te]

    mk = np.abs(y_tr) <= MAX_LABEL
    X_tr, y_tr = X_tr[mk], y_tr[mk]
    mk_va = np.abs(y_va) <= MAX_LABEL
    X_va, y_va = X_va[mk_va], y_va[mk_va]
    mk_te = np.abs(y_te) <= MAX_LABEL
    X_te, y_te = X_te[mk_te], y_te[mk_te]
    print(f"  训练：{len(X_tr):,}  验证：{len(X_va):,}  测试：{len(X_te):,}", flush=True)

    # 标准化
    ns = {}
    for j in range(N_FEATS):
        v = X_tr[:, j]
        v = v[~np.isnan(v) & ~np.isinf(v)]
        if len(v) < 100: continue
        lo, hi = float(np.percentile(v, 0.5)), float(np.percentile(v, 99.5))
        ns[f'feat_{j}'] = {
            'mean': float(np.mean(v)),
            'std': float(np.std(v, ddof=1)),
            'low': lo, 'high': hi
        }

    def norm(Xi):
        Xo = Xi.copy()
        for j in range(N_FEATS):
            k = f'feat_{j}'
            if k in ns and ns[k]['std'] > 0:
                s = ns[k]
                Xo[:, j] = np.clip(Xo[:, j], s['low'], s['high'])
                Xo[:, j] = (Xo[:, j] - s['mean']) / s['std']
        return Xo

    # 训练
    print("\nTrain 训练...", flush=True)
    model = lgb.train({
        'objective': 'regression', 'metric': 'l2',
        'learning_rate': 0.02, 'num_leaves': 127, 'max_depth': 10,
        'feature_fraction': 0.7, 'bagging_fraction': 0.8,
        'bagging_freq': 5, 'min_data_in_leaf': 50,
        'num_threads': 8, 'verbosity': -1, 'seed': 42
    }, lgb.Dataset(norm(X_tr), y_tr.astype(np.float32)),
       num_boost_round=5000,
       valid_sets=[lgb.Dataset(norm(X_va), y_va.astype(np.float32))],
       valid_names=['val'],
       callbacks=[lgb.early_stopping(100), lgb.log_evaluation(200)])
    bi = model.best_iteration

    def ev(Xs, yt):
        p = model.predict(Xs, num_iteration=bi)
        ic = spearmanr(p, yt)[0]
        o = np.argsort(p)
        n = len(o)
        return {
            'ic': round(ic, 4),
            'd1': round(np.mean(yt[o[:n//10]]), 2),
            'd10': round(np.mean(yt[o[-n//10:]]), 2),
            'spread': round(np.mean(yt[o[-n//10:]]) - np.mean(yt[o[:n//10]]), 2)
        }

    tr = ev(norm(X_tr), y_tr)
    va = ev(norm(X_va), y_va)
    te = ev(norm(X_te), y_te)
    print(f"\n{'指标':<16} {'训练':>8} {'验证':>8} {'测试':>8}", flush=True)
    print(f"{'─'*40}", flush=True)
    for k in ['ic', 'd1', 'd10', 'spread']:
        print(f"{k:<16} {tr[k]:>8} {va[k]:>8} {te[k]:>8}", flush=True)

    # 保存
    out_name = 'lgb_reg_20d_v7_pc.txt'
    model.save_model(str(MODEL_DIR / out_name))
    with open(MODEL_DIR / 'v7_norm_stats_pc.json', 'w') as f:
        json.dump(ns, f, indent=2)

    # 特征重要性
    imp = sorted(zip(range(N_FEATS), model.feature_importance('gain')), key=lambda x: -x[1])
    print(f"\nF 特征重要性 TOP10:", flush=True)
    for col, gain in imp[:10]:
        gt = f' tushare_{col-38}' if col >= 38 else ''
        print(f"  列{col:>2}{gt}: {gain/1e6:.2f}M ({gain/model.feature_importance('gain').sum()*100:.1f}%)", flush=True)

    nonzero_feats = sum(1 for _, g in imp if g > 0)
    print(f"\n  有效特征：{nonzero_feats}/{N_FEATS}", flush=True)
    top5_pct = sum(g for _, g in imp[:5]) / sum(g for _, g in imp) * 100
    print(f"  TOP5 集中度：{top5_pct:.1f}%", flush=True)

    print(f"\nSave 保存：{out_name} ({bi}棵，IC={te['ic']})", flush=True)
    print(f"Time {time.time()-t0:.0f}s", flush=True)

    conn.close()

if __name__ == '__main__':
    main()
