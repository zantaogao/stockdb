#!/usr/bin/env python3
"""统一训练脚本 — 支持 10d/20d/40d 不同窗口和特征集

MODEL = '10d' | '20d' | '40d'
"""
import json, sys, time, math
import numpy as np
import lightgbm as lgb
from pathlib import Path
from scipy.stats import spearmanr, skew, kurtosis
sys.stdout.reconfigure(line_buffering=True)

BASE = Path.home() / '.hermes' / 'stockdb'
MODEL_DIR = BASE / 'models'
DB_PATH = BASE / 'state.db'

# ═══════════════════════ 模型配置 ═══════════════════════
CONFIGS = {
    'cls': {
        'fwd_days': 10, 'window': 120,
        'split_train': '2025-01-01', 'split_val': '2025-06-01',
        'lr': 0.02, 'leaves': 63, 'min_data': 50,
        'rounds': 3000, 'early_stop': 150,
        'max_label': 50.0,
        'objective': 'binary', 'metric': 'auc',
        'exclude_feats': [3, 4, 8, 9, 25, 32],  # 同10d特征
        'suffix': 'v1',
    },
    '10d': {
        'fwd_days': 10, 'window': 120,
        'split_train': '2025-01-01', 'split_val': '2025-06-01',
        'lr': 0.02, 'leaves': 63, 'min_data': 200,
        'rounds': 3000, 'early_stop': 0,
        'max_label': 50.0,
        'objective': 'regression',
        'exclude_feats': [3, 4, 8, 9, 20, 21, 22, 25, 32],  # 去掉长周期+估值
        'suffix': 'v2',
    },
    '20d': {
        'fwd_days': 20, 'window': 120,
        'split_train': '2025-01-01', 'split_val': '2025-06-01',
        'lr': 0.01, 'leaves': 64, 'min_data': 100,
        'rounds': 8000, 'early_stop': 150,
        'max_label': 50.0,
        'objective': 'regression',
        'exclude_feats': [4, 9, 20, 21, 22],
        'suffix': 'v9',
    },
    '20d10': {
        'fwd_days': 20, 'window': 120,
        'split_train': '2025-01-01', 'split_val': '2025-06-01',
        'lr': 0.01, 'leaves': 64, 'min_data': 100,
        'rounds': 8000, 'early_stop': 150,
        'max_label': 50.0,
        'objective': 'regression',
        'exclude_feats': [],  # 49维全量，含换手率/资金流/行业相对
        'suffix': 'v10',
    },
    '40d': {
        'fwd_days': 40, 'window': 120,
        'split_train': '2025-01-01', 'split_val': '2025-06-01',
        'lr': 0.01, 'leaves': 64, 'min_data': 100,
        'rounds': 8000, 'early_stop': 150,
        'max_label': 50.0,
        'objective': 'regression',
        'exclude_feats': [],
        'suffix': 'v8',
    },
    '40d9': {
        'fwd_days': 40, 'window': 120,
        'split_train': '2025-01-01', 'split_val': '2025-06-01',
        'lr': 0.01, 'leaves': 64, 'min_data': 100,
        'rounds': 8000, 'early_stop': 150,
        'max_label': 50.0,
        'objective': 'regression',
        'exclude_feats': [],  # 位置20/21/22已被替换为换手率/资金流，不需排除
        'suffix': 'v9',
    },
    '40d11': {
        'fwd_days': 40, 'window': 120,
        'split_train': '2025-01-01', 'split_val': '2025-06-01',
        'lr': 0.01, 'leaves': 64, 'min_data': 100,
        'rounds': 8000, 'early_stop': 150,
        'max_label': 50.0,
        'objective': 'regression',
        'exclude_feats': [],
        'suffix': 'v11',
    },
}
# ═══════════════════════════════════════════════════════

MASK_EXCLUDE = CONFIGS[sys.argv[1] if len(sys.argv) > 1 else '20d']
FWD_DAYS = MASK_EXCLUDE['fwd_days']
WINDOW = MASK_EXCLUDE['window']
SPLIT_TRAIN = MASK_EXCLUDE['split_train']
SPLIT_VAL = MASK_EXCLUDE['split_val']
MAX_LABEL = MASK_EXCLUDE['max_label']
EXCLUDE = MASK_EXCLUDE['exclude_feats']
SUFFIX = MASK_EXCLUDE['suffix']

# 基础特征38维名称映射（用于判断排除的是哪个）
FEAT_NAMES_38 = [
    'chg5','chg10','chg20','chg60','chg120',
    'd5','d10','d20','d60','d120',
    'bull1','bull2',
    'rr','std20','vr','pos','nh','vpc',
    'c1d','c3d',
    'ep','bp','ln_cap',
    'ex5','ex10','ex20',
    'skew20','kurt20','dn_streak','up_ratio10','vol_chg','rel_str',
    'kurt60','slope5','slope10','accel','vp_shrink','vp_div',
] + ['turn_rate','turn_ratio','mf_net_lg','ind_chg20','ind_chg60'] + [f'GTJA_{i}' for i in range(1,12)]

# 49维全量特征掩码（默认全开）
N_TOTAL = 49 + (5 if SUFFIX in ('v10', 'v11') else 0)
FEAT_KEEP = np.ones(N_TOTAL, dtype=bool)
for idx in EXCLUDE:
    FEAT_KEEP[idx] = False
    tag = FEAT_NAMES_38[idx] if idx < 38 else f'GTJA_{idx-37}'
    print(f"  ✂ 排除特征 [{idx:>2}] {tag}", flush=True)

N_FEATS_FINAL = int(FEAT_KEEP.sum())
print(f"  最终特征: {N_FEATS_FINAL} 维 ({49-N_FEATS_FINAL}个被排除)", flush=True)

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
    rows = conn.execute("""
        SELECT date, close FROM index_daily
        WHERE index_code='000001' ORDER BY date
    """).fetchall()
    return {str(r[0])[:10]: float(r[1]) for r in rows}


def main():
    t0 = time.time()
    label = f"{FWD_DAYS}d回归重训{SUFFIX} — {WINDOW}天窗口, {N_FEATS_FINAL}维"
    print("=" * 65, flush=True)
    print(label, flush=True)
    print(f"  切分: {SPLIT_TRAIN}/{SPLIT_VAL}", flush=True)
    print("=" * 65, flush=True)

    import duckdb
    conn = duckdb.connect(str(Path.home() / '.hermes' / 'stockdb' / 'state.db')_PATH), read_only=True)

    stocks = [r[0] for r in conn.execute("""
        SELECT stock_code FROM stock_info
        WHERE stock_code NOT LIKE '8%%' AND stock_code NOT LIKE '4%%'
        AND market!='北交所' AND (stock_name NOT LIKE '%%ST%%' OR stock_name IS NULL)
    """).fetchall()]
    print(f"\n股票: {len(stocks)}", flush=True)

    vm = load_valmap(conn)
    print(f"估值: {len(vm)} 条", flush=True)

    idx_close = load_index_close(conn)
    print(f"指数: {len(idx_close)} 个交易日", flush=True)

    # ── SQL特征 ──
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
    print(f"  有效: {n_v:,}", flush=True)

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
    print(f"  原始特征: {raw.shape}  y: {y.shape}", flush=True)

    # ── 38维F_base ──
    n = len(codes)
    N_BASE = 38 + (5 if SUFFIX == 'v11' else 0)
    F = np.zeros((n, N_BASE), dtype=np.float64)
    F[:, 0] = raw[:, 0]; F[:, 1] = raw[:, 1]; F[:, 2] = raw[:, 2]
    F[:, 3] = raw[:, 3]; F[:, 4] = raw[:, 4]
    F[:, 5] = raw[:, 5]; F[:, 6] = raw[:, 6]; F[:, 7] = raw[:, 7]
    F[:, 8] = raw[:, 8]; F[:, 9] = raw[:, 9]
    F[:, 10] = raw[:, 10]; F[:, 11] = raw[:, 11]
    F[:, 18] = raw[:, 12]; F[:, 19] = raw[:, 13]
    print(f"  38维F_base 初始化完成", flush=True)

    # ── 超额收益 ──
    print("\n📡 超额收益计算...", flush=True)
    idt_sorted = sorted(idx_close.keys())
    dt_to_pos = {d: i for i, d in enumerate(idt_sorted)}
    n_idx = len(idt_sorted)
    idx_cl = np.array([idx_close[d] for d in idt_sorted], dtype=np.float64)
    idx_ret_5 = np.full(n_idx, np.nan)
    idx_ret_10 = np.full(n_idx, np.nan)
    idx_ret_20 = np.full(n_idx, np.nan)
    for i in range(5, n_idx): idx_ret_5[i] = idx_cl[i] / idx_cl[i-5] - 1
    for i in range(10, n_idx): idx_ret_10[i] = idx_cl[i] / idx_cl[i-10] - 1
    for i in range(20, n_idx): idx_ret_20[i] = idx_cl[i] / idx_cl[i-20] - 1
    ex5_arr, ex10_arr, ex20_arr = np.zeros(n), np.zeros(n), np.zeros(n)
    for i in range(n):
        dt = dates[i]
        pos = dt_to_pos.get(dt)
        if pos is not None:
            ex5_arr[i] = F[i, 0] - (idx_ret_5[pos] if not np.isnan(idx_ret_5[pos]) else 0)
            ex10_arr[i] = F[i, 1] - (idx_ret_10[pos] if not np.isnan(idx_ret_10[pos]) else 0)
            ex20_arr[i] = F[i, 2] - (idx_ret_20[pos] if not np.isnan(idx_ret_20[pos]) else 0)
    F[:, 23] = ex5_arr; F[:, 24] = ex10_arr; F[:, 25] = ex20_arr
    print(f"  超额收益已填充: ex5={np.nanmean(ex5_arr):.4f} ex10={np.nanmean(ex10_arr):.4f} ex20={np.nanmean(ex20_arr):.4f}", flush=True)

    # ── 逐股票特征 ──
    print("\n🔨 per-stock 特征...", flush=True)
    unique_codes = list(dict.fromkeys(codes))
    code_to_idx = {}
    for i, c in enumerate(codes):
        code_to_idx.setdefault(c, []).append(i)

    all_close = conn.execute("""
        SELECT stock_code, date, close, volume
        FROM stock_daily ORDER BY stock_code, date
    """).fetchall()
    sd = {}
    for code, dt, close, vol in all_close:
        sd.setdefault(code, []).append((str(dt)[:10], float(close), float(vol or 0)))
    conn.close()

    gtja_c, gtja_n = None, []
    cp = MODEL_DIR / 'gtja_compact.pkl'
    if cp.exists():
        import pickle
        with open(cp, 'rb') as f:
            gtja_c = pickle.load(f)
        gtja_n = sorted(gtja_c.keys())[:11]
        print(f"  GTJA: {len(gtja_n)} 个因子", flush=True)
    else:
        print("  ⚠️ 无 GTJA 数据", flush=True)

    gtja_cols = np.zeros((n, 11), dtype=np.float64)

    # 加载换手率和资金流（仅40d_v9需要）
    USE_NEW_FEATS = SUFFIX in ('v9', 'v11')
    turn_map, mf_map = {}, {}
    if USE_NEW_FEATS:
        conn2 = duckdb.connect(str(DB_PATH), read_only=True)
        tr = conn2.execute("""
            SELECT ts_code, trade_date, turnover_rate
            FROM daily_basic WHERE trade_date >= '20200101'
        """).fetchall()
        for tc, td, tr_val in tr:
            code = tc.split('.')[0]
            dt = str(td)[:10]
            if float(tr_val or 0) > 0:
                turn_map[(code, dt)] = float(tr_val)
        mfr = conn2.execute("""
            SELECT ts_code, trade_date,
                   COALESCE(buy_lg_amount,0)+COALESCE(buy_elg_amount,0) as buy_lg,
                   COALESCE(sell_lg_amount,0)+COALESCE(sell_elg_amount,0) as sell_lg,
                   COALESCE(buy_sm_amount,0)+COALESCE(buy_md_amount,0) as buy_retail,
                   COALESCE(sell_sm_amount,0)+COALESCE(sell_md_amount,0) as sell_retail
            FROM moneyflow_raw WHERE trade_date >= '20200101'
        """).fetchall()
        for tc, td, bl, sl, br, sr in mfr:
            code = tc.split('.')[0]
            dt = str(td)[:10]
            tot = bl+sl+br+sr
            if tot > 0:
                mf_map.setdefault(code, {})[dt] = (bl-sl)/tot*100  # 净大单占比%
        conn2.close()
        print(f"  换手率: {len(turn_map)} 条", flush=True)
        print(f"  资金流: {len(unique_codes)} only", flush=True)

        # 行业相对强弱
        print("  Industry relative strength...", flush=True)
        conn3 = duckdb.connect(str(DB_PATH), read_only=True)
        ind_rows = conn3.execute("""
            SELECT stock_code, industry FROM stock_info
            WHERE industry IS NOT NULL AND industry != ''
        """).fetchall()
        stock_to_ind = {r[0]: r[1] for r in ind_rows}
        daily_ret = conn3.execute("""
            SELECT stock_code, date, COALESCE(change_pct,0)/100
            FROM stock_daily ORDER BY stock_code, date
        """).fetchall()
        # 按日期+行业计算均值
        ind_daily_ret = {}  # {(industry, date): mean_return}
        from collections import defaultdict
        by_date_ind = defaultdict(list)
        for code, dt, ret in daily_ret:
            dt_s = str(dt)[:10]
            ind = stock_to_ind.get(code)
            if ind:
                by_date_ind[(ind, dt_s)].append(ret)
        for (ind, dt_s), rets in by_date_ind.items():
            ind_daily_ret[(ind, dt_s)] = sum(rets)/len(rets)
        print(f"  行业日均收益: {len(ind_daily_ret):,} 条")
        conn3.close()
    for si, code in enumerate(unique_codes):
        idxs = code_to_idx[code]
        r = sd.get(code, [])
        if not r: continue
        r_d = [x[0] for x in r]
        c = np.array([x[1] for x in r])
        v = np.array([x[2] for x in r])
        nsd = len(c)
        p = np.zeros(nsd); p[1:] = (c[1:] - c[:-1]) / c[:-1]
        dm = {d: i for i, d in enumerate(r_d)}
        gs = {}
        if gtja_c:
            for gn in gtja_n: gs[gn] = gtja_c.get(gn, {}).get(code, {})
        for j, idx in enumerate(idxs):
            dt = dates[idx]
            di = dm.get(dt)
            if di is None or di < 120: continue
            w = c[max(0, di - 119):di + 1]
            lc = w[-1]
            p20 = p[max(0, di - 19):di + 1]
            w20 = w[-20:]
            rl, rh = np.min(w20), np.max(w20)
            F[idx, 12] = (rh - rl) / rl * 100 if rl > 0 else 0
            F[idx, 13] = np.std(w20) / np.mean(w20) * 100 if np.mean(w20) > 0 else 0
            vw = v[max(0, di - 19):di + 1]
            F[idx, 14] = vw[-1] / np.mean(vw) if np.mean(vw) > 0 else 1
            F[idx, 15] = (lc - rl) / (rh - rl) * 100 if rh != rl else 50
            F[idx, 16] = 1 if lc > rh * 0.97 else 0
            chg5 = F[idx, 0]
            F[idx, 17] = 1 if chg5 > 0.01 and F[idx, 14] > 1.2 else 0
            ve = vm.get((code, dt), {})
            if SUFFIX == 'v9':
                # v9: 替换估值→换手率/资金流
                tr_val = turn_map.get((code, dt), 0)
                F[idx, 20] = tr_val  # turn_rate
                # 换手率20日均值比
                tr_vals = [turn_map.get((code, dt2), 0) for dt2 in r_d[max(0, di-19):di+1]]
                tr_mean = sum(tr_vals)/len(tr_vals) if tr_vals else 1
                F[idx, 21] = tr_val / tr_mean if tr_mean > 0 else 1  # turn_ratio_20d
                F[idx, 22] = mf_map.get(code, {}).get(dt, 0)  # mf_net_lg
            else:
                F[idx, 20] = ve.get('ep', 0.5); F[idx, 21] = ve.get('bp', 0.5); F[idx, 22] = ve.get('ln_cap', 22.0)
            if not USE_NEW_FEATS:
                F[idx, 26] = float(skew(w20)) if len(w20) >= 20 else 0
            elif SUFFIX == 'v9':
                # v9: mf_net_5d at 26
                mf_5d_vals = [mf_map.get(code, {}).get(r_d[j], 0)
                              for j in range(max(0, di-4), di+1) if j < len(r_d)]
                F[idx, 26] = sum(mf_5d_vals)/len(mf_5d_vals) if mf_5d_vals else 0
            else:
                # v10/v11: keep skew20 at 26 (new features at 38-42)
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
            else: F[idx, 30] = 0
            ma20 = np.mean(w20)
            ma60 = np.mean(c[max(0, di - 59):di + 1]) if di >= 59 else ma20
            F[idx, 31] = chg5 - (ma20 / ma60 - 1) if ma60 > 0 else 0
            w60 = c[max(0, di - 59):di + 1]
            if SUFFIX == 'v9':
                ind = stock_to_ind.get(code)
                ind_rets_60 = [ind_daily_ret.get((ind, r_d[j]), 0) for j in range(max(0, di-59), di+1) if j < len(r_d)]
                stock_ret_60 = (lc / c[max(0, di-59)] - 1) if c[max(0, di-59)] > 0 else 0
                ind_avg_60 = sum(ind_rets_60) / len(ind_rets_60) if ind_rets_60 else 0
                F[idx, 32] = stock_ret_60 - ind_avg_60
            else:
                F[idx, 32] = float(kurtosis(w60, fisher=False)) if len(w60) >= 60 else 3
            if len(w20) >= 10:
                x5 = np.arange(5); y5 = w20[-5:]
                s5 = float(np.sum((x5 - x5.mean()) * (y5 - y5.mean())) / np.sum((x5 - x5.mean())**2)) if np.sum((x5 - x5.mean())**2) > 0 else 0
                x10 = np.arange(10); y10 = w20[-10:]
                s10 = float(np.sum((x10 - x10.mean()) * (y10 - y10.mean())) / np.sum((x10 - x10.mean())**2)) if np.sum((x10 - x10.mean())**2) > 0 else 0
                F[idx, 33] = s5; F[idx, 34] = s10; F[idx, 35] = s5 - s10
            else: F[idx, 33] = F[idx, 34] = F[idx, 35] = 0
            vw20 = v[max(0, di - 19):di + 1]
            vr20 = vw20[-1] / np.mean(vw20) if np.mean(vw20) > 0 else 1
            F[idx, 36] = 1 if chg5 < -0.01 and vr20 < 0.7 else 0
            F[idx, 37] = 1 if (chg5 > 0 and vr20 < 0.8) or (chg5 < 0 and vr20 > 1.2) else 0

            if SUFFIX == 'v11':
                # 38-42: 换手率/换手率比/大单净流入/行业相对20d/行业相对60d
                tr_v = turn_map.get((code, dt), 0)
                F[idx, 38] = tr_v
                tr_vs = [turn_map.get((code, r_d[j2]), 0) for j2 in range(max(0, di-19), di+1) if j2 < len(r_d)]
                tr_m = sum(tr_vs)/len(tr_vs) if tr_vs else 1
                F[idx, 39] = tr_v/tr_m if tr_m>0 else 1
                F[idx, 40] = mf_map.get(code, {}).get(dt, 0)
                ind = stock_to_ind.get(code)
                ir20 = [ind_daily_ret.get((ind, r_d[j2]), 0) for j2 in range(max(0, di-19), di+1) if j2 < len(r_d)]
                sr20 = (lc / c[max(0, di-19)] - 1) if c[max(0, di-19)] > 0 else 0
                ia20 = sum(ir20)/len(ir20) if ir20 else 0
                F[idx, 41] = sr20 - ia20
                ir60 = [ind_daily_ret.get((ind, r_d[j2]), 0) for j2 in range(max(0, di-59), di+1) if j2 < len(r_d)]
                sr60 = (lc / c[max(0, di-59)] - 1) if c[max(0, di-59)] > 0 else 0
                ia60 = sum(ir60)/len(ir60) if ir60 else 0
                F[idx, 42] = sr60 - ia60
            for gi, gn in enumerate(gtja_n[:11]):
                val = gs.get(gn, {}).get(dt, 0.0)
                gtja_cols[idx, gi] = val
        if (si + 1) % 500 == 0:
            print(f"  [{si+1}/{len(unique_codes)}] {time.time()-t0:.0f}s", flush=True)

    # ── 合并 + 特征选择 ──
    N_FULL = 49 + (5 if SUFFIX == 'v11' else 0)
    X_full = np.column_stack([F, gtja_cols])[:, :N_FULL]
    X_full = np.nan_to_num(X_full, nan=0.0, posinf=0.0, neginf=0.0)
    X = X_full[:, FEAT_KEEP]
    print(f"\n  X全量: {X_full.shape} → 筛选后: {X.shape}", flush=True)

    # GTJA截断（winsorize 1%-99%）
    gtja_start = 43 if SUFFIX == 'v11' else 38
    for j in range(gtja_start, N_FULL):
        if not FEAT_KEEP[j]: continue
        col = X_full[:, j]
        if np.count_nonzero(col) < 100: continue
        lo, hi = np.percentile(col[col != 0], [1, 99])
        X_full[:, j] = np.clip(col, lo, hi)
    X = X_full[:, FEAT_KEEP]

    # ── 切分 ──
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

    # ── 标准化 ──
    ns = {}
    for j in range(N_FEATS_FINAL):
        v = X_tr[:, j]; v = v[~np.isnan(v) & ~np.isinf(v)]
        if len(v) < 100: continue
        lo, hi = float(np.percentile(v, 0.5)), float(np.percentile(v, 99.5))
        ns[f'feat_{j}'] = {'mean': float(np.mean(v)), 'std': float(np.std(v, ddof=1)), 'low': lo, 'high': hi}

    def norm(Xi):
        Xo = Xi.copy()
        for j in range(N_FEATS_FINAL):
            k = f'feat_{j}'
            if k in ns and ns[k]['std'] > 0:
                s = ns[k]
                Xo[:, j] = np.clip(Xo[:, j], s['low'], s['high'])
                Xo[:, j] = (Xo[:, j] - s['mean']) / s['std']
        return Xo

    # ── 训练 ──
    print("\n🏋️ 训练...", flush=True)
    IS_CLS = MASK_EXCLUDE['objective'] == 'binary'
    if IS_CLS:
        y_tr = (y_tr > 0).astype(np.float32)
        y_va = (y_va > 0).astype(np.float32)
        y_te = (y_te > 0).astype(np.float32)
        pos = y_tr.sum()
        neg = len(y_tr) - pos
        w = np.where(y_tr == 1, neg / pos, 1.0)
        print(f"  分类: 正={int(pos)} 负={int(neg)} 比例={pos/neg:.3f}", flush=True)

    params = {
        'objective': MASK_EXCLUDE['objective'],
        'metric': MASK_EXCLUDE.get('metric', 'l2'),
        'learning_rate': MASK_EXCLUDE['lr'],
        'num_leaves': MASK_EXCLUDE['leaves'],
        'max_depth': 8,
        'feature_fraction': 0.7, 'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'min_data_in_leaf': MASK_EXCLUDE['min_data'],
        'num_threads': 8, 'verbosity': -1, 'seed': 42,
    }

    train_set = lgb.Dataset(norm(X_tr), y_tr.astype(np.float32), weight=w if IS_CLS else None)
    valid_sets = [lgb.Dataset(norm(X_va), y_va.astype(np.float32))]
    valid_names = ['val']

    if MASK_EXCLUDE['early_stop'] > 0:
        model = lgb.train(params, train_set,
            num_boost_round=MASK_EXCLUDE['rounds'],
            valid_sets=valid_sets, valid_names=valid_names,
            callbacks=[lgb.early_stopping(MASK_EXCLUDE['early_stop']), lgb.log_evaluation(200)])
        bi = model.best_iteration
    else:
        model = lgb.train(params, train_set,
            num_boost_round=MASK_EXCLUDE['rounds'],
            valid_sets=valid_sets, valid_names=valid_names,
            callbacks=[lgb.log_evaluation(200)])
        bi = MASK_EXCLUDE['rounds']

    def ev(Xs, yt):
        p = model.predict(Xs, num_iteration=bi)
        if IS_CLS:
            from sklearn.metrics import roc_auc_score
            auc = roc_auc_score(yt, p)
            return {'auc': round(auc, 4)}
        ic = spearmanr(p, yt)[0]
        o = np.argsort(p); n = len(o)
        return {'ic': round(ic, 4), 'd1': round(np.mean(yt[o[:n//10]]), 2),
                'd10': round(np.mean(yt[o[-n//10:]]), 2),
                'spread': round(np.mean(yt[o[-n//10:]]) - np.mean(yt[o[:n//10]]), 2)}

    tr = ev(norm(X_tr), y_tr)
    te = ev(norm(X_te), y_te)
    va = ev(norm(X_va), y_va) if len(X_va) > 0 else {'auc': 0} if IS_CLS else {'ic': 0, 'd1': 0, 'd10': 0, 'spread': 0}
    print(f"\n{'指标':<16} {'训练':>8} {'验证':>8} {'测试':>8}", flush=True)
    print(f"{'─'*40}", flush=True)
    key_list = ['auc'] if IS_CLS else ['ic', 'd1', 'd10', 'spread']
    for k in key_list:
        print(f"{k:<16} {tr[k]:>8} {va[k]:>8} {te[k]:>8}", flush=True)

    # ── 保存 ──
    prefix = 'lgb_cls' if IS_CLS else 'lgb_reg'
    out_name = f'{prefix}_{FWD_DAYS}d_{SUFFIX}.txt'
    model.save_model(str(MODEL_DIR / out_name))
    ns_name = f'norm_stats_{FWD_DAYS}d_{SUFFIX}.json' if not IS_CLS else f'norm_stats_cls_{FWD_DAYS}d_{SUFFIX}.json'
    with open(MODEL_DIR / ns_name, 'w') as f:
        json.dump(ns, f, indent=2)

    # 特征重要性（映射回原始索引）
    orig_imp = np.zeros(N_FULL)
    keep_idx = np.where(FEAT_KEEP)[0]
    for i, gain in enumerate(model.feature_importance('gain')):
        orig_imp[keep_idx[i]] = gain

    imp = sorted(zip(range(N_FULL), orig_imp), key=lambda x: -x[1])
    print(f"\n📊 特征重要性 TOP10:", flush=True)
    for col, gain in imp[:10]:
        if gain == 0: continue
        if col < 38:
            name = FEAT_NAMES_38[col]
        elif col < 43:
            name = ['turn_rate','turn_ratio','mf_net_lg','ind_chg20','ind_chg60'][col-38]
        else:
            name = f'GTJA_{col-42}'
        excluded = ' [已排除]' if not FEAT_KEEP[col] else ''
        print(f"  列{col:>2} {name:<12s}: {gain/1e6:.2f}M ({gain/orig_imp.sum()*100:.1f}%){excluded}", flush=True)

    nonzero_feats = sum(1 for _, g in imp if g > 0)
    print(f"\n  有效特征: {nonzero_feats}/{N_FULL} (筛选后{N_FEATS_FINAL})", flush=True)
    top5_pct = sum(g for _, g in imp[:5]) / max(sum(g for _, g in imp), 1) * 100
    print(f"  TOP5集中度: {top5_pct:.1f}%", flush=True)
    final_metric = f"AUC={te['auc']}" if IS_CLS else f"IC={te['ic']}"
    print(f"\n💾 保存: {out_name} ({bi}棵, {final_metric})", flush=True)
    print(f"⏱ {time.time()-t0:.0f}s", flush=True)

    # 保存训练结果到 JSON
    result = {
        'model': out_name,
        'trees': bi,
        'feats': N_FEATS_FINAL,
        'time_sec': int(time.time() - t0),
        'objective': MASK_EXCLUDE['objective'],
        'split_train': SPLIT_TRAIN,
        'split_val': SPLIT_VAL,
    }
    if IS_CLS:
        result['test_auc'] = te['auc']
        result['train_auc'] = tr['auc']
        result['val_auc'] = va.get('auc', 0)
    else:
        result['test_ic'] = te['ic']
        result['train_ic'] = tr['ic']
        result['val_ic'] = va.get('ic', 0)
        result['test_spread'] = te.get('spread', 0)
        result['test_d10'] = te.get('d10', 0)
    with open(MODEL_DIR / f'train_result_{FWD_DAYS}d_{SUFFIX}.json', 'w') as f:
        json.dump(result, f, indent=2)


if __name__ == '__main__':
    main()
