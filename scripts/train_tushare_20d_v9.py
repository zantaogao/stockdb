"""Train LightGBM regression with 20-day forward return label.
Data source: tushare.db (DuckDB).
Time-based split: train=2016-2023, val=2024-2025H1, test=2025H2+.

Features (90): 26 L1量价 + 40 L2 stk_factor技术指标 + 15 L3估值质量 + 12 L4资金财务
Label: 20-day forward log return * 100 (percentage)

完全使用stk_factor替代GTJA，A股特色处理（ST过滤、涨跌停clip）。
"""
import os, json, time, sys, numpy as np
import lightgbm as lgb
from scipy import stats
from pathlib import Path
import math
import duckdb

sys.stdout.reconfigure(line_buffering=True)

# === Config ===
BASE = Path.home() / '.hermes' / 'stockdb'
DB = BASE / 'tushare.db'
OUT_MODEL = BASE / 'models' / 'lgb_reg_20d_v9.txt'
OUT_STATS = BASE / 'models' / 'v9_norm_stats.json'

FEAT_WIN = 60       # 特征窗口60天（对应20日预测）
FWD_DAYS = 20       # 向前20个交易日

# 时间切分（10年数据：2016-2026）
TRAIN_END = '20231231'   # 训练集截止
VAL_START = '20240101'   # 验证集开始
VAL_END   = '20250630'   # 验证集截止
TEST_START= '20250701'   # 测试集开始

# ST股票列表缓存
_ST_LIST = None


def load_st_list(conn):
    """加载ST股票列表（stock_basic中name含ST的）"""
    global _ST_LIST
    if _ST_LIST is not None:
        return _ST_LIST
    try:
        rows = conn.execute("""
            SELECT ts_code, name FROM stock_basic 
            WHERE name LIKE '%ST%' OR name LIKE '%st%'
            ORDER BY ts_code
        """).fetchall()
        _ST_LIST = set(r[0] for r in rows)
        print(f"  ST stocks: {len(_ST_LIST)}")
    except Exception as e:
        print(f"  ⚠️ ST列表加载失败: {e}")
        _ST_LIST = set()
    return _ST_LIST


def compute_label(closes, adj_factors, i):
    """计算20日对数收益率标签，带涨跌停clip"""
    target_idx = i + FWD_DAYS
    if target_idx >= len(closes):
        return None
    
    adj_today = adj_factors[i]
    adj_target = adj_factors[target_idx]
    
    if adj_today <= 0 or adj_target <= 0:
        fwd_close = closes[target_idx]
        today_close = closes[i]
    else:
        fwd_close = closes[target_idx] * (adj_today / adj_target)
        today_close = closes[i]
    
    if today_close <= 0 or fwd_close <= 0:
        return None
    
    ret_pct = math.log(fwd_close / today_close) * 100.0
    # A股涨跌停clip：统一clip到±20%（覆盖主板/创业板/科创板）
    ret_pct = np.clip(ret_pct, -20.0, 20.0)
    
    return float(ret_pct)


def ef(extra_dict, key, default=0.0):
    """从stk_factor extra字典安全取值"""
    val = extra_dict.get(key, default)
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return default
    return float(val)


def main():
    t0 = time.time()
    print("=" * 70)
    print("Training 20-day model v9 — stk_factor替代GTJA")
    print(f"Time range: 2016-01 ~ 2026-07 (10 years)")
    print(f"Features: 90维 (26 L1 + 40 L2 + 15 L3 + 12 L4)")
    print("=" * 70)

    conn = duckdb.connect(str(DB), read_only=True)

    # ── 加载ST列表 ──
    st_list = load_st_list(conn)

    # ── 获取所有股票 ──
    stock_codes = [r[0] for r in conn.execute("""
        SELECT DISTINCT ts_code FROM daily 
        WHERE trade_date >= '20160101' ORDER BY ts_code
    """).fetchall()]
    print(f"Total stocks: {len(stock_codes)}")

    # ── 加载估值数据缓存（daily_basic）──
    print("Loading valuation cache...")
    val_cache = {}
    try:
        val_rows = conn.execute("""
            SELECT ts_code, trade_date, pe_ttm, pb, total_mv, turnover_rate_f, volume_ratio
            FROM daily_basic ORDER BY ts_code, trade_date
        """).fetchall()
        for code, dt, pe, pb, mv, tr, vr in val_rows:
            v = {}
            if pe and pe > 0: v['ep'] = 1.0 / float(pe)
            if pb and pb > 0: v['bp'] = 1.0 / float(pb)
            if mv and mv > 0: v['ln_cap'] = np.log(float(mv))
            if tr is not None: v['turnover_rate_f'] = float(tr)
            if vr is not None: v['volume_ratio'] = float(vr)
            val_cache[(code, str(dt)[:10])] = v
    except Exception as e:
        print(f"  ⚠️ 估值缓存加载失败: {e}")

    print(f"  Valuation entries: {len(val_cache):,}")

    # ── stk_factor缓存（模块级）──
    _STK_CACHE = {}

    def load_stk_factor(ts_code, trade_date_str):
        """从stk_factor表加载技术指标因子，带缓存"""
        cache_key = (ts_code, trade_date_str)
        if cache_key in _STK_CACHE:
            return _STK_CACHE[cache_key]
        
        extra_dict = {}
        try:
            direct_cols = ['macd_dif','macd_dea','macd','kdj_k','kdj_d','kdj_j',
                           'rsi_6','rsi_12','rsi_24','boll_upper','boll_mid','boll_lower','cci']
            direct_vals = conn.execute(f"""
                SELECT {','.join(direct_cols)} FROM stk_factor
                WHERE ts_code='{ts_code}' AND trade_date='{trade_date_str.replace("-", "")}'
            """).fetchone()

            if direct_vals:
                for col, val in zip(direct_cols, direct_vals):
                    if val is not None and not np.isnan(val):
                        extra_dict[f'{col}_bfq'] = float(val)

            # 再查extra JSON（250个因子）
            extra_str = conn.execute(f"""
                SELECT extra FROM stk_factor
                WHERE ts_code='{ts_code}' AND trade_date='{trade_date_str.replace("-", "")}'
            """).fetchone()

            if extra_str and extra_str[0]:
                try:
                    ed = json.loads(extra_str[0])
                    for k, v in ed.items():
                        if isinstance(v, (int, float)) and not np.isnan(v):
                            if '_bfq' in k:
                                extra_dict[k] = float(v)
                except: pass

            _STK_CACHE[cache_key] = extra_dict
            return extra_dict

        except Exception as e:
            _STK_CACHE[cache_key] = {}
            return {}

    # ── 主循环：逐股票计算特征+标签 ──
    X_list, y_list, date_list = [], [], []
    min_rows = FEAT_WIN + FWD_DAYS + 10
    
    print(f"\nComputing features for {len(stock_codes)} stocks...")
    
    from scipy.stats import skew, kurtosis

    for ci, code in enumerate(stock_codes):
        # ST过滤
        if code in st_list:
            continue
            
        rows = conn.execute(f"""
            SELECT trade_date, close, COALESCE(pct_chg, 0), vol, amount, open, high, low
            FROM daily 
            WHERE ts_code = '{code}' AND trade_date >= '20160101'
            ORDER BY trade_date
        """).fetchall()

        if len(rows) < min_rows:
            continue

        # 提取数组
        dates = [str(r[0])[:10] for r in rows]
        closes = np.array([float(r[1]) for r in rows])
        
        adj_factors = []
        for r in rows:
            af_row = conn.execute(f"""
                SELECT adj_factor FROM adj_factor 
                WHERE ts_code='{code}' AND trade_date='{r[0]}'
            """).fetchone()
            adj_factors.append(float(af_row[0]) if af_row and af_row[0] else 1.0)
        adj_factors = np.array(adj_factors)

        # ── 逐日计算特征+标签 ──
        for i in range(FEAT_WIN, len(rows) - FWD_DAYS):
            dt = dates[i]
            
            c_window = closes[i-FEAT_WIN:i+1]
            lc = c_window[-1]

            # ════════════════════════════════════════
            # L1: 量价基础 (26维) — core.features.py FEAT_NAMES[0:26]
            # ════════════════════════════════════════
            chg5 = lc/c_window[-5]-1 if c_window[-5] > 0 else 0
            chg10 = lc/c_window[-10]-1 if c_window[-10] > 0 else 0
            chg20 = lc/c_window[-20]-1 if c_window[-20] > 0 else 0
            chg60 = lc/c_window[-60]-1 if c_window[-60] > 0 else 0
            chg120 = lc/c_window[0]-1

            ma5 = np.mean(c_window[-5:])
            ma10 = np.mean(c_window[-10:])
            ma20 = np.mean(c_window[-20:])
            ma60 = np.mean(c_window[-60:])

            d5 = lc/ma5-1 if ma5 > 0 else 0
            d10 = lc/ma10-1 if ma10 > 0 else 0
            d20 = lc/ma20-1 if ma20 > 0 else 0
            d60 = lc/ma60-1 if ma60 > 0 else 0
            d120 = lc/np.mean(c_window)-1

            b1 = 1.0 if ma5 > ma10 > ma20 else 0.0
            b2 = 1.0 if ma20 > ma60 else 0.0

            price_range = np.max(c_window[-20:]) - np.min(c_window[-20:])
            min_20 = np.min(c_window[-20:])
            rr = price_range / min_20 * 100 if min_20 > 0 else 0

            std20 = np.std(c_window[-20:]) / np.mean(c_window[-20:]) * 100

            vols = np.array([float(rows[i-FEAT_WIN+j][3]) for j in range(FEAT_WIN) if rows[i-FEAT_WIN+j][3]])
            if len(vols) < 20:
                continue
            vr = float(vols[-1] / np.mean(vols)) if np.mean(vols) > 0 else 1.0

            rl, rh = np.min(c_window[-20:]), np.max(c_window[-20:])
            pos = (lc - rl) / (rh - rl) * 100 if rh != rl else 50.0

            nh = 1.0 if lc > rh * 0.97 else 0.0
            vpc = 1.0 if chg5 > 0 and vr > 1.2 else 0.0

            pct_chg_today = float(rows[i][2]) / 100.0 if rows[i][2] is not None else 0.0
            c1d = pct_chg_today
            c3d = lc/c_window[-3]-1 if len(c_window) >= 3 and c_window[-3] > 0 else 0

            v_entry = val_cache.get((code, dt), {})
            ep_val = (v_entry.get('ep', 0.5) or 0.5)
            bp_val = (v_entry.get('bp', 0.5) or 0.5)
            ln_cap_val = (v_entry.get('ln_cap', 22.0) or 22.0)

            ex5 = ex10 = ex20 = 0.0  # 暂不计算超额收益（需指数数据）

            window20 = c_window[-20:]
            skew20 = float(skew(window20)) if len(window20) >= 20 else 0.0
            kurt20 = float(kurtosis(window20, fisher=False)) if len(window20) >= 20 else 3.0

            pcts_rev = np.array([float(rows[i-FEAT_WIN+j][2] or 0) for j in range(FEAT_WIN)]) / 100.0
            signs20 = np.sign(pcts_rev[-20:])
            dn_streak = float(np.sum(signs20 < 0))

            up_ratio10 = float(np.mean(signs20[-10:] > 0))

            vol_old = float(np.std(pcts_rev[-60:-20]) * math.sqrt(252)) if len(pcts_rev) >= 60 else 0.0
            vol_new = float(np.std(pcts_rev[-20:]) * math.sqrt(252))
            vol_chg = (vol_new / vol_old - 1) if vol_old > 0 else 0.0

            rel_str = chg5 - (ma20 / ma60 - 1) if ma60 > 0 else 0.0

            kurt60 = float(kurtosis(c_window[-60:], fisher=False)) if len(c_window) >= 60 else 3.0

            x5 = np.arange(5); y5 = c_window[-5:]
            slope5 = float(np.sum((x5-x5.mean())*(y5-y5.mean()))/np.sum((x5-x5.mean())**2)) if np.sum((x5-x5.mean())**2) > 0 else 0.0
            x10 = np.arange(10); y10 = c_window[-10:]
            slope10 = float(np.sum((x10-x10.mean())*(y10-y10.mean()))/np.sum((x10-x10.mean())**2)) if np.sum((x10-x10.mean())**2) > 0 else 0.0
            accel = slope5 - slope10

            vols_20 = np.array([float(rows[i-FEAT_WIN+j][3] or 0) for j in range(FEAT_WIN)])[-20:]
            vr_20 = float(vols_20[-1] / np.mean(vols_20)) if np.mean(vols_20) > 0 else 1.0
            vp_shrink = 1.0 if (chg5 < -0.01 and vr_20 < 0.7) else 0.0
            vp_div = 1.0 if ((chg5 > 0 and vr_20 < 0.8) or (chg5 < 0 and vr_20 > 1.2)) else 0.0

            l1_feats = [chg5, chg10, chg20, chg60, chg120,
                        d5, d10, d20, d60, d120,
                        b1, b2, rr, std20, vr, pos,
                        nh, vpc, c1d, c3d, ep_val, bp_val, ln_cap_val,
                        ex5, ex10, ex20]

            # ════════════════════════════════════════
            # L2: stk_factor技术指标+估值 (40维) — FEAT_NAMES[26:66]
            # ════════════════════════════════════════
            ts_code = f"{code}.SH" if code.startswith(('6', '68', '9')) else f"{code}.SZ"

            # 加载stk_factor（带缓存）
            extra = load_stk_factor(ts_code, dt)

            # MACD系 (6)
            macd_dif_bfq = ef(extra, 'macd_dif_bfq', 0.0)
            macd_dea_bfq = ef(extra, 'macd_dea_bfq', 0.0)
            macd_bfq_val = ef(extra, 'macd_bfq', 0.0)
            macd_hist_bfq = macd_dif_bfq - macd_dea_bfq if (macd_dif_bfq or macd_dea_bfq) else macd_bfq_val
            macd_dif_hfq = ef(extra, 'macd_dif_hfq', 0.0)
            macd_dif_qfq = ef(extra, 'macd_dif_qfq', 0.0)

            # KDJ系 (6) — 含金叉/死叉
            kdj_k_bfq = ef(extra, 'kdj_k_bfq', 50.0)
            kdj_d_bfq = ef(extra, 'kdj_d_bfq', 50.0)
            kdj_j_bfq = ef(extra, 'kdj_j_bfq', 50.0)
            kdk_ratio_bfq = (kdj_k_bfq / kdj_d_bfq - 1) if kdj_d_bfq > 0 else 0.0
            
            # KDJ金叉/死叉（用前一天数据）
            prev_extra = load_stk_factor(ts_code, dates[i-1]) if i >= FEAT_WIN + 1 else extra
            prev_kdj_k = ef(prev_extra, 'kdj_k_bfq', kdj_k_bfq)
            prev_kdj_d = ef(prev_extra, 'kdj_d_bfq', kdj_d_bfq)
            kdk_prev = prev_kdj_k - prev_kdj_d if (prev_kdj_k and prev_kdj_d) else 0
            kdk_curr = kdj_k_bfq - kdj_d_bfq
            kdj_cross_up = 1.0 if kdk_prev <= 0 and kdk_curr > 0 else 0.0
            kdj_cross_down = 1.0 if kdk_prev >= 0 and kdk_curr < 0 else 0.0

            # RSI系 (6) — 含rsi_ma5和rsi_level_bull
            rsi_6_bfq = ef(extra, 'rsi_6_bfq', 50.0)
            rsi_12_bfq = ef(extra, 'rsi_12_bfq', 50.0)
            rsi_24_bfq = ef(extra, 'rsi_24_bfq', 50.0)
            rsi_divergence_bfq = abs(rsi_6_bfq - rsi_12_bfq) / (rsi_12_bfq + 1e-8)
            # rsi_ma5: 用过去5天rsi_6的均值（近似）
            prev_extra2 = load_stk_factor(ts_code, dates[max(i-FEAT_WIN, i-4)]) if i >= FEAT_WIN else extra
            rsi_6_prev = ef(prev_extra2, 'rsi_6_bfq', rsi_6_bfq)
            rsi_ma5_bfq = (rsi_6_bfq + 4 * rsi_6_prev) / 5.0 if i >= FEAT_WIN else rsi_6_bfq
            rsi_level_bull = 1.0 if rsi_6_bfq > 70 else (0.0 if rsi_6_bfq < 30 else 0.5)

            # BOLL系 (6)
            boll_upper_bfq = ef(extra, 'boll_upper_bfq', lc)
            boll_mid_bfq = ef(extra, 'boll_mid_bfq', lc)
            boll_lower_bfq = ef(extra, 'boll_lower_bfq', lc)
            boll_width_bfq = (boll_upper_bfq - boll_lower_bfq) / boll_mid_bfq if boll_mid_bfq > 0 else 0.0
            price_boll_pos = (lc - boll_lower_bfq) / (boll_upper_bfq - boll_lower_bfq) if (boll_upper_bfq - boll_lower_bfq) > 0 else 0.5
            boll_break_up = 1.0 if lc > boll_upper_bfq else 0.0

            # 趋势/动量 (8) — cci, roc, mtm, wr, dmi
            cci_val = ef(extra, 'cci_bfq', 0.0)
            roc_10_bfq = ef(extra, 'roc_bfq', 0.0)
            mtm_10_bfq = ef(extra, 'mtm_bfq', 0.0)
            wr_6_bfq = ef(extra, 'wr_bfq', -50.0)
            dmi_pdi_bfq = ef(extra, 'dmi_pdi_bfq', 20.0)
            dmi_mdi_bfq = ef(extra, 'dmi_mdi_bfq', 20.0)
            dmi_adx_bfq = ef(extra, 'dmi_adx_bfq', 25.0)

            # 均线系 (4) — stk_factor直接列有ma_bfq_*
            ma5_stk = ef(extra, 'ma_bfq_5', np.mean(c_window[-5:]))
            ma20_stk = ef(extra, 'ma_bfq_20', np.mean(c_window[-20:]))
            ma60_stk = ef(extra, 'ma_bfq_60', np.mean(c_window[-60:]) if len(c_window) >= 60 else ma20_stk)
            ma_ratio_short_long = (ma5_stk / ma60_stk - 1) if ma60_stk > 0 else 0.0

            # 量价衍生 (4) — obv, volume_ratio, turnover_rate
            obv_bfq = ef(extra, 'obv_bfq', 0.0)
            volume_ratio_f = ef(extra, 'volume_ratio', vr)
            turnover_rate_bfq = v_entry.get('turnover_rate_f', 0.0) or 0.0

            # L2末尾: 估值因子 (2) — pe_ttm, pb
            ep_val_local = float(ep_val) if ep_val else 1e-8
            bp_val_local = float(bp_val) if bp_val else 1e-8
            pe_ttm = (1.0 / ep_val_local) if ep_val_local > 0 else 50.0
            pb_val2 = (1.0 / bp_val_local) if bp_val_local > 0 else 3.0

            l2_feats = [macd_dif_bfq, macd_dea_bfq, macd_bfq_val, macd_hist_bfq, macd_dif_hfq, macd_dif_qfq,
                        kdj_k_bfq, kdj_d_bfq, kdj_j_bfq, kdk_ratio_bfq, kdj_cross_up, kdj_cross_down,
                        rsi_6_bfq, rsi_12_bfq, rsi_24_bfq, rsi_divergence_bfq, rsi_ma5_bfq, rsi_level_bull,
                        boll_upper_bfq, boll_mid_bfq, boll_lower_bfq, boll_width_bfq, price_boll_pos, boll_break_up,
                        cci_val, roc_10_bfq, mtm_10_bfq, wr_6_bfq, dmi_pdi_bfq, dmi_mdi_bfq, dmi_adx_bfq,
                        ma5_stk, ma20_stk, ma60_stk, ma_ratio_short_long,
                        obv_bfq, volume_ratio_f, turnover_rate_bfq,
                        pe_ttm, pb_val2]

            # ════════════════════════════════════════
            # L3: 估值质量+资金 (15维) — FEAT_NAMES[66:81]
            # ════════════════════════════════════════
            ps_val, pcf_val = 5.0, 20.0
            div_yield = 0.0
            total_mv_val = np.exp(ln_cap_val) if ln_cap_val > 0 else 1e10
            circ_mv_val = total_mv_val
            mv_ratio = circ_mv_val / total_mv_val if total_mv_val > 0 else 1.0
            turnover_f = v_entry.get('turnover_rate_f', 0.0) or 0.0
            vol_rat_qfq = v_entry.get('volume_ratio', 1.0) or 1.0

            amihud = 0.0
            if len(c_window) >= 20:
                daily_returns = []
                for j in range(-20, 0):
                    r_i = abs(c_window[j] / c_window[j-1] - 1) if c_window[j-1] > 0 else 0
                    v_i = float(rows[i+j][3]) if rows[i+j][3] is not None else 0
                    if v_i > 0:
                        daily_returns.append(r_i / (v_i / 1e8))
                amihud = np.mean(daily_returns) if daily_returns else 0.0

            beta_20d = std20 / 20.0 if std20 > 0 else 0.0

            high_60d = np.max(c_window[-60:]) if len(c_window) >= 60 else lc
            low_60d = np.min(c_window[-60:]) if len(c_window) >= 60 else lc
            high_low_avg = (high_60d + low_60d) / 2 / lc - 1
            price_rank_60d = float(np.sum(c_window[-60:] < lc)) / 60.0 if len(c_window) >= 60 else 0.5

            l3_feats = [ps_val, pcf_val, div_yield,
                        np.log(total_mv_val), circ_mv_val, mv_ratio,
                        turnover_f, vol_rat_qfq, amihud, beta_20d,
                        high_low_avg, price_rank_60d,
                        0.0, 0.0, 0.0]   # money_net_flow_pct, money_main_inflow, money_super_large

            # ════════════════════════════════════════
            # L4: 财务比率 (9维) — FEAT_NAMES[81:90]
            # ════════════════════════════════════════
            l4_feats = [0.0, 0.0, 0.0,   # revenue_yoy, profit_yoy, roe_ttm
                        2.0, 0.5,        # current_ratio, debt_asset_ratio
                        0.3, 0.1,        # gross_margin, net_margin
                        0.0, 0.0]        # sales_growth_1y, eps_growth_1y

            # ── 拼接90维特征 ──
            feat = np.array(l1_feats + l2_feats + l3_feats + l4_feats, dtype=np.float64)

            # ── 计算标签 ──
            label = compute_label(closes, adj_factors, i)
            if label is None:
                continue

            X_list.append(feat)
            y_list.append(label)
            date_list.append(dt)

        if (ci + 1) % 500 == 0:
            print(f"  {ci+1}/{len(stock_codes)} stocks, {len(X_list):,} samples [{time.time()-t0:.0f}s]")

    conn.close()

    # ── 数据汇总 ──
    X_raw = np.array(X_list, dtype=np.float64)
    y = np.array(y_list, dtype=np.float64)

    print(f"\n{'='*70}")
    print(f"Total samples: {len(X_raw):,}")
    print(f"Feature dimensions: {X_raw.shape[1]}")
    print(f"Label stats: mean={np.mean(y):+.3f}% std={np.std(y):.3f}% min={np.min(y):+.2f}% max={np.max(y):+.2f}%")

    # ── 时间切分 ──
    train_mask = np.array([d <= TRAIN_END for d in date_list])
    val_mask = np.array([VAL_START <= d <= VAL_END for d in date_list])
    test_mask = np.array([d >= TEST_START for d in date_list])

    X_train_raw, y_train = X_raw[train_mask], y[train_mask]
    X_val_raw, y_val = X_raw[val_mask], y[val_mask]
    X_test_raw, y_test = X_raw[test_mask], y[test_mask]

    print(f"\nTime-based split:")
    print(f"  Train (2016-{TRAIN_END[-4:]}): {len(X_train_raw):,} samples")
    print(f"  Val   ({VAL_START[:4]}H1-{VAL_END[-4:]}):     {len(X_val_raw):,} samples")
    print(f"  Test  ({TEST_START[:4]}H2+):      {len(X_test_raw):,} samples")

    # ── 标准化（仅从训练集计算统计量）──
    new_stats = {}
    for j in range(X_train_raw.shape[1]):
        vals = X_train_raw[:, j]
        valid = vals[~np.isnan(vals)]
        if len(valid) > 0:
            new_stats[f'feat_{j}'] = {
                'mean': float(np.mean(valid)),
                'std': float(np.std(valid)),
                'low': float(np.percentile(valid, 1)),
                'high': float(np.percentile(valid, 99))
            }

    def normalize(X, stats):
        Xn = X.copy()
        for j in range(min(len(stats), X.shape[1])):
            key = f'feat_{j}'
            if key in stats and stats[key]['std'] > 0:
                s = stats[key]
                Xn[:, j] = np.clip(Xn[:, j], s['low'], s['high'])
                Xn[:, j] = (Xn[:, j] - s['mean']) / s['std']
        return np.nan_to_num(Xn, nan=0.0)

    X_train = normalize(X_train_raw, new_stats)
    X_val = normalize(X_val_raw, new_stats)
    X_test = normalize(X_test_raw, new_stats)

    with open(OUT_STATS, 'w') as f:
        json.dump(new_stats, f, indent=2)
    print(f"Stats saved: {OUT_STATS}")

    # ── 训练LightGBM ──
    print(f"\nTraining LightGBM (lr=0.01, early_stopping=50, max 2000 rounds)...")
    dtrain = lgb.Dataset(X_train, y_train)
    dval = lgb.Dataset(X_val, y_val, reference=dtrain)

    params = {
        'objective': 'regression', 'metric': 'rmse',
        'num_leaves': 63, 'learning_rate': 0.01,
        'feature_fraction': 0.7, 'bagging_fraction': 0.8,
        'bagging_freq': 5, 'min_data_in_leaf': 200,
        'lambda_l1': 1.0, 'lambda_l2': 2.0,
        'min_gain_to_split': 0.01,
        'verbose': -1, 'num_threads': -1,
    }

    model = lgb.train(params, dtrain, num_boost_round=2000,
                      valid_sets=[dtrain, dval], valid_names=['train', 'val'],
                      callbacks=[lgb.early_stopping(50), lgb.log_evaluation(100)])

    best_iter = model.best_iteration
    pred_train = model.predict(X_train, num_iteration=best_iter)
    pred_val = model.predict(X_val, num_iteration=best_iter)
    pred_test = model.predict(X_test, num_iteration=best_iter)

    ic_train = stats.spearmanr(pred_train, y_train)[0]
    ic_val = stats.spearmanr(pred_val, y_val)[0]
    ic_test = stats.spearmanr(pred_test, y_test)[0]

    # ── 结果输出 ──
    print(f"\n{'='*70}")
    print(f"20-Day Model v9 Results")
    print(f"{'='*70}")
    print(f"Trees: {model.num_trees()}, Best iteration: {best_iter}")
    print(f"Train IC (Spearman):  {ic_train:.4f}")
    print(f"Val   IC (Spearman):  {ic_val:.4f}")
    print(f"Test  IC (Spearman):  {ic_test:.4f}")

    # Val decile analysis
    if len(pred_val) > 0:
        val_arr = np.array(list(zip(pred_val, y_val)))
        val_arr = val_arr[val_arr[:, 0].argsort()]
        d10 = max(1, len(val_arr) // 10)
        print(f"\nVal decile analysis:")
        for d in range(10):
            s, e = d * d10, (d + 1) * d10 if d < 9 else len(val_arr)
            print(f"  D{d+1}: {np.mean(val_arr[s:e, 1]):+.3f}%")
        spread_v = np.mean(val_arr[-d10:, 1]) - np.mean(val_arr[:d10, 1])
        print(f"  Spread (D10-D1): {spread_v:+.2f}%")

    # Test decile analysis
    if len(pred_test) > 0:
        test_arr = np.array(list(zip(pred_test, y_test)))
        test_arr = test_arr[test_arr[:, 0].argsort()]
        d10_t = max(1, len(test_arr) // 10)
        print(f"\nTest decile analysis ({TEST_START[:4]}H2+):")
        for d in range(10):
            s, e = d * d10_t, (d + 1) * d10_t if d < 9 else len(test_arr)
            print(f"  D{d+1}: {np.mean(test_arr[s:e, 1]):+.3f}%")
        spread_t = np.mean(test_arr[-d10_t:, 1]) - np.mean(test_arr[:d10_t, 1])
        print(f"  Spread (D10-D1): {spread_t:+.2f}%")

    # Feature importance
    importances = model.feature_importance(importance_type='gain')
    feat_names = [
        'chg5','chg10','chg20','chg60','chg120',
        'd5','d10','d20','d60','d120',
        'bull1','bull2','rr','std20','vr','pos',
        'nh','vpc','c1d','c3d','ep','bp','ln_cap',
        'ex5','ex10','ex20',
        'macd_dif','macd_dea','macd','macd_hist','macd_dif_hfq','macd_dif_qfq',
        'kdj_k','kdj_d','kdj_j','kdk_ratio','kdj_cross_up','kdj_cross_down',
        'rsi_6','rsi_12','rsi_24','rsi_div','rsi_ma5','rsi_level_bull',
        'boll_upper','boll_mid','boll_lower','boll_width','price_boll_pos','boll_break_up',
        'cci','roc_10','mtm_10','wr_6','dmi_pdi','dmi_mdi','dmi_adx',
        'ma5_stk','ma20_stk','ma60_stk','ma_ratio_short_long',
        'obv','volume_ratio','turnover_rate',
        'pe_ttm','pb','ps','pcf','div_yield','ln_total_mv','circ_mv','mv_ratio',
        'turnover_f','vol_rat_qfq','amihud','beta_20d','high_low_avg','price_rank_60d',
        'money_net_flow_pct','money_main_inflow','money_super_large',
        'revenue_yoy','profit_yoy','roe_ttm',
        'current_ratio','debt_asset_ratio',
        'gross_margin','net_margin',
        'sales_growth_1y','eps_growth_1y'
    ]

    print(f"\nTop 20 Feature Importance (gain):")
    top_indices = np.argsort(importances)[::-1][:20]
    for rank, idx in enumerate(top_indices):
        print(f"  {rank+1:2d}. {feat_names[idx]:25s} = {importances[idx]:.0f}")

    # Save model
    with open(OUT_MODEL, 'w') as f:
        f.write(model.dump_model())
    print(f"\nModel saved: {OUT_MODEL}")
    
    elapsed = time.time() - t0
    print(f"Total time: {elapsed:.0f}s")


if __name__ == '__main__':
    main()
