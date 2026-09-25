#!/usr/bin/env python3
"""40d回归重训 v6 — 120天窗口, 49维(38基础+11GTJA), 修复特征问题

修复项:
  1. tushare.db (非 stock.db)
  2. 加载指数数据，ex5/ex10/ex20 不再=0
  3. 120天窗口，chg120/d120 真实计算
  4. GTJA全部加载，不做前向填充
  5. 估值数据来自 tushare.db (完整)
"""
import json, os, sys, time, math
import numpy as np
import lightgbm as lgb
from pathlib import Path
from scipy.stats import spearmanr, skew, kurtosis
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).parent.parent))
import duckdb

BASE = Path.home() / '.hermes' / 'stockdb'
MODEL_DIR = BASE / 'models'
DB_PATH = BASE / 'state.db'
SPLIT_TRAIN = '2025-01-01'
SPLIT_VAL = '2025-06-01'
FWD_DAYS = 40
MAX_LABEL = 50.0
N_FEATS = 49  # 38基础+11GTJA
WINDOW = 120  # 120天

def load_valmap(conn):
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
    """加载上证指数收盘价（用于超额收益计算）"""
    rows = conn.execute("""
        SELECT date, close FROM index_daily
        WHERE index_code='000001' ORDER BY date
    """).fetchall()
    return {str(r[0])[:10]: float(r[1]) for r in rows}


def main():
    t0 = time.time()
    print("=" * 65, flush=True)
    print(f"40d回归重训 v6 — {WINDOW}天窗口, {N_FEATS}维 (修复版)", flush=True)
    print(f"  切分: {SPLIT_TRAIN}/{SPLIT_VAL}", flush=True)
    print("=" * 65, flush=True)

    conn = duckdb.connect(str(Path.home() / '.hermes' / 'stockdb' / 'state.db')_PATH), read_only=True)
    
    stocks = [r[0] for r in conn.execute("""
        SELECT stock_code FROM stock_info
        WHERE stock_code NOT LIKE '8%' AND stock_code NOT LIKE '4%'
        AND market!='北交所' AND (stock_name NOT LIKE '%ST%' OR stock_name IS NULL)
    """).fetchall()]
    print(f"\n股票: {len(stocks)}", flush=True)

    vm = load_valmap(conn)
    print(f"估值: {len(vm)} 条", flush=True)

    idx_close = load_index_close(conn)
    print(f"指数: {len(idx_close)} 个交易日", flush=True)

    # SQL窗口函数(WINDOW天)算基础特征
    print("\n🔨 SQL特征...", flush=True)
    conn.execute(f"""
        CREATE TEMP TABLE feats AS
        SELECT s.stock_code, s.date,
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
            (LEAD(s.close, {FWD_DAYS}) OVER w / s.close - 1) * 100 \"label\",
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
    print(f"  有效: {n_v:,}", flush=True)

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
    raw = raw[:, :-1]  # 14列: chg5,chg10,chg20,chg60,chg120,d5,d10,d20,d60,d120,bull1,bull2,c1d,c3d
    print(f"  原始特征: {raw.shape}  y: {y.shape}", flush=True)

    # 重建38维F_base
    n = len(codes)
    F = np.zeros((n, 38), dtype=np.float64)
    # 0-4: chg5,chg10,chg20,chg60,chg120 (真实数据!)
    F[:, 0] = raw[:, 0]   # chg5
    F[:, 1] = raw[:, 1]   # chg10
    F[:, 2] = raw[:, 2]   # chg20
    F[:, 3] = raw[:, 3]   # chg60
    F[:, 4] = raw[:, 4]   # chg120 ✅ 真实值
    # 5-9: d5,d10,d20,d60,d120 (真实数据!)
    F[:, 5] = raw[:, 5]   # d5
    F[:, 6] = raw[:, 6]   # d10
    F[:, 7] = raw[:, 7]   # d20
    F[:, 8] = raw[:, 8]   # d60
    F[:, 9] = raw[:, 9]   # d120 ✅ 真实值
    # 10-11: bull1,bull2
    F[:, 10] = raw[:, 10]
    F[:, 11] = raw[:, 11]
    # 18-19: c1d,c3d
    F[:, 18] = raw[:, 12]
    F[:, 19] = raw[:, 13]
    print(f"  38维F_base 初始化完成 (chg120/d120修正, 待补超额收益)", flush=True)

    # 补充超额收益 (ex5/ex10/ex20) — 优化版
    print("\n📡 超额收益计算...", flush=True)
    # 预计算指数每日收益
    idt_sorted = sorted(idx_close.keys())
    idt_set = set(idt_sorted)
    # 日期→索引映射
    dt_to_pos = {d: i for i, d in enumerate(idt_sorted)}
    n_idx = len(idt_sorted)
    idx_cl = np.array([idx_close[d] for d in idt_sorted], dtype=np.float64)
    
    # 预计算指数各周期收益
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
        # else 保持0
    
    F[:, 23] = ex5_arr
    F[:, 24] = ex10_arr
    F[:, 25] = ex20_arr
    print(f"  超额收益已填充: ex5={np.nanmean(ex5_arr):.4f} ex10={np.nanmean(ex10_arr):.4f} ex20={np.nanmean(ex20_arr):.4f}", flush=True)

    # 补充剩余特征
    print("\n🔨 per-stock 特征...", flush=True)
    unique_codes = list(dict.fromkeys(codes))
    code_to_idx = {}
    for i, c in enumerate(codes):
        code_to_idx.setdefault(c, []).append(i)

    # 加载行情
    all_close = conn.execute("""
        SELECT stock_code, date, close, volume
        FROM stock_daily ORDER BY stock_code, date
    """).fetchall()
    sd = {}
    for code, dt, close, vol in all_close:
        sd.setdefault(code, []).append((str(dt)[:10], float(close), float(vol or 0)))
    conn.close()

    # 加载GTJA
    gtja_c, gtja_n = None, []
    cp = MODEL_DIR / 'gtja_compact.pkl'
    if cp.exists():
        import pickle
        with open(cp, 'rb') as f:
            gtja_c = pickle.load(f)
        gtja_n = sorted(gtja_c.keys())[:11]
        print(f"  GTJA: {len(gtja_n)} 个因子", flush=True)
    else:
        print("  ⚠️ 无 GTJA 数据，用0填充", flush=True)

    gtja_cols = np.zeros((n, 11), dtype=np.float64)

    for si, code in enumerate(unique_codes):
        idxs = code_to_idx[code]
        r = sd.get(code, [])
        if not r: continue
        r_d = [x[0] for x in r]
        c = np.array([x[1] for x in r])
        v = np.array([x[2] for x in r])
        nsd = len(c)
        p = np.zeros(nsd)
        p[1:] = (c[1:] - c[:-1]) / c[:-1]
        dm = {d: i for i, d in enumerate(r_d)}

        # GTJA 快速查找
        gs = {}
        if gtja_c:
            for gn in gtja_n:
                gs[gn] = gtja_c.get(gn, {}).get(code, {})

        for j, idx in enumerate(idxs):
            dt = dates[idx]
            di = dm.get(dt)
            if di is None or di < 120:  # 需要至少120天数据
                continue

            w = c[max(0, di - 119):di + 1]
            lc = w[-1]
            p20 = p[max(0, di - 19):di + 1]
            w20 = w[-20:]
            rl, rh = np.min(w20), np.max(w20)

            # 12-17: rr, std20, vr, pos, nh, vpc
            F[idx, 12] = (rh - rl) / rl * 100 if rl > 0 else 0
            F[idx, 13] = np.std(w20) / np.mean(w20) * 100 if np.mean(w20) > 0 else 0
            vw = v[max(0, di - 19):di + 1]
            F[idx, 14] = vw[-1] / np.mean(vw) if np.mean(vw) > 0 else 1
            F[idx, 15] = (lc - rl) / (rh - rl) * 100 if rh != rl else 50
            F[idx, 16] = 1 if lc > rh * 0.97 else 0
            chg5 = F[idx, 0]
            F[idx, 17] = 1 if chg5 > 0.01 and F[idx, 14] > 1.2 else 0

            # 20-22: ep, bp, ln_cap
            ve = vm.get((code, dt), {})
            F[idx, 20] = ve.get('ep', 0.5)
            F[idx, 21] = ve.get('bp', 0.5)
            F[idx, 22] = ve.get('ln_cap', 22.0)

            # 26-31: skew20, kurt20, dn_streak, up_ratio10, vol_chg, rel_str
            F[idx, 26] = float(skew(w20)) if len(w20) >= 20 else 0
            F[idx, 27] = float(kurtosis(w20, fisher=False)) if len(w20) >= 20 else 3
            stk = 0
            for s in reversed(np.sign(p20)):
                if s < 0: stk += 1
                else: break
            F[idx, 28] = stk
            F[idx, 29] = np.sum(np.sign(p20[-10:]) > 0) / 10.0 if len(p20) >= 10 else 0.5
            if di >= 60:
                vo = float(np.std(p[max(0, di - 59):di - 19]) * math.sqrt(252))
                vn = float(np.std(p20) * math.sqrt(252))
                F[idx, 30] = vn / vo - 1 if vo > 0 else 0
            else:
                F[idx, 30] = 0
            ma20 = np.mean(w20)
            ma60 = np.mean(c[max(0, di - 59):di + 1]) if di >= 59 else ma20
            F[idx, 31] = chg5 - (ma20 / ma60 - 1) if ma60 > 0 else 0

            # 32-37: kurt60, slope5, slope10, accel, vp_shrink, vp_div
            w60 = c[max(0, di - 59):di + 1]
            F[idx, 32] = float(kurtosis(w60, fisher=False)) if len(w60) >= 60 else 3
            if len(w20) >= 10:
                x5 = np.arange(5)
                y5 = w20[-5:]
                s5 = float(np.sum((x5 - x5.mean()) * (y5 - y5.mean())) / np.sum((x5 - x5.mean())**2)) if np.sum((x5 - x5.mean())**2) > 0 else 0
                x10 = np.arange(10)
                y10 = w20[-10:]
                s10 = float(np.sum((x10 - x10.mean()) * (y10 - y10.mean())) / np.sum((x10 - x10.mean())**2)) if np.sum((x10 - x10.mean())**2) > 0 else 0
                F[idx, 33] = s5
                F[idx, 34] = s10
                F[idx, 35] = s5 - s10
            else:
                F[idx, 33] = F[idx, 34] = F[idx, 35] = 0
            vw20 = v[max(0, di - 19):di + 1]
            vr20 = vw20[-1] / np.mean(vw20) if np.mean(vw20) > 0 else 1
            F[idx, 36] = 1 if chg5 < -0.01 and vr20 < 0.7 else 0
            F[idx, 37] = 1 if (chg5 > 0 and vr20 < 0.8) or (chg5 < 0 and vr20 > 1.2) else 0

            # GTJA — 当前日期的值
            for gi, gn in enumerate(gtja_n[:11]):
                val = gs.get(gn, {}).get(dt, 0.0)
                gtja_cols[idx, gi] = val

        if (si + 1) % 500 == 0:
            print(f"  [{si+1}/{len(unique_codes)}] {time.time()-t0:.0f}s", flush=True)

    # 合并特征
    X = np.column_stack([F, gtja_cols])[:, :N_FEATS]
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    print(f"\n  X: {X.shape}", flush=True)

    # 检查哪些列是全0或常数
    for j in range(N_FEATS):
        col = X[:, j]
        nonzero = np.count_nonzero(col)
        if nonzero < 100:
            print(f"  ⚠️ 列{j} (GTJA_{j-37 if j>=38 else j}) 几乎全0: {nonzero}/{len(X)} 个非零", flush=True)

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
    print(f"  训练: {len(X_tr):,}  验证: {len(X_va):,}  测试: {len(X_te):,}", flush=True)

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
    print("\n🏋️ 训练...", flush=True)
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
    out_name = 'lgb_reg_40d_v6_fixed.txt'
    model.save_model(str(MODEL_DIR / out_name))
    with open(MODEL_DIR / 'v6_norm_stats_40d_v6_fixed.json', 'w') as f:
        json.dump(ns, f, indent=2)

    # 特征重要性
    imp = sorted(zip(range(N_FEATS), model.feature_importance('gain')), key=lambda x: -x[1])
    print(f"\n📊 特征重要性 TOP10:", flush=True)
    for col, gain in imp[:10]:
        gt = f' GTJA_{col-37}' if col >= 38 else ''
        print(f"  列{col:>2}{gt}: {gain/1e6:.2f}M ({gain/model.feature_importance('gain').sum()*100:.1f}%)", flush=True)

    nonzero_feats = sum(1 for _, g in imp if g > 0)
    print(f"\n  有效特征: {nonzero_feats}/{N_FEATS}", flush=True)
    top5_pct = sum(g for _, g in imp[:5]) / sum(g for _, g in imp) * 100
    print(f"  TOP5集中度: {top5_pct:.1f}%", flush=True)

    print(f"\n💾 保存: {out_name} ({bi}棵, IC={te['ic']})", flush=True)
    print(f"⏱ {time.time()-t0:.0f}s", flush=True)


if __name__ == '__main__':
    main()
