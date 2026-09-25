"""
统一特征计算 — 机构级因子体系（93维）

四层因子：
  L1: 量价基础 (26维) — daily表衍生
  L2: stk_factor技术指标 (40维) — 从stk_factor直接列+extra JSON提取
  L3: 估值质量 (15维) — daily_basic + stock_valuation
  L4: 资金+财务 (12维) — money_flow + fin_income + fina_indicator

总计: 93维（不含标签）
"""
import numpy as np
from pathlib import Path
from scipy.stats import skew, kurtosis
import math
import duckdb
import json

BASE = Path.home() / '.hermes' / 'stockdb'

# ═══════════════════════════════════════════════════════════
# 特征名称列表（93维）
# ═══════════════════════════════════════════════════════════
FEAT_NAMES = [
    # ── L1: 量价基础 (26维) ──
    'chg5', 'chg10', 'chg20', 'chg60', 'chg120',
    'd5', 'd10', 'd20', 'd60', 'd120',
    'bull1', 'bull2', 'rr', 'std20', 'vr', 'pos',
    'nh', 'vpc', 'c1d', 'c3d', 'ep', 'bp', 'ln_cap',
    'ex5', 'ex10', 'ex20',

    # ── L2: stk_factor技术指标 (40维) ──
    # MACD系 (6)
    'macd_dif_bfq', 'macd_dea_bfq', 'macd_bfq',
    'macd_hist_bfq', 'macd_dif_hfq', 'macd_dif_qfq',
    # KDJ系 (6)
    'kdj_k_bfq', 'kdj_d_bfq', 'kdj_j_bfq',
    'kdk_ratio_bfq', 'kdj_cross_up', 'kdj_cross_down',
    # RSI系 (6)
    'rsi_6_bfq', 'rsi_12_bfq', 'rsi_24_bfq',
    'rsi_divergence_bfq', 'rsi_ma5_bfq', 'rsi_level_bull',
    # BOLL系 (6)
    'boll_upper_bfq', 'boll_mid_bfq', 'boll_lower_bfq',
    'boll_width_bfq', 'price_boll_pos', 'boll_break_up',
    # 趋势/动量 (8)
    'cci_bfq', 'roc_10_bfq', 'mtm_10_bfq',
    'wr_6_bfq', 'dmi_pdi_bfq', 'dmi_mdi_bfq', 'dmi_adx_bfq',
    # 均线系 (4)
    'ma5_bfq', 'ma20_bfq', 'ma60_bfq', 'ma_ratio_short_long',
    # 量价衍生 (4)
    'obv_bfq', 'volume_ratio_f', 'turnover_rate_bfq',

    # ── L3: 估值质量 (15维) ──
    'pe_ttm', 'pb', 'ps_ttm', 'pcf_ttm',
    'dividend_yield', 'total_mv', 'circ_mv', 'mv_ratio',
    'turnover_rate_f', 'volume_ratio_qfq',
    'amihud_illiq', 'beta_20d',
    'high_low_avg', 'price_rank_60d',

    # ── L4: 资金+财务 (12维) ──
    'money_net_flow_pct', 'money_main_inflow', 'money_super_large',
    'revenue_yoy', 'profit_yoy', 'roe_ttm',
    'current_ratio', 'debt_asset_ratio',
    'gross_margin', 'net_margin',
    'sales_growth_1y', 'eps_growth_1y',
]

N_FEATURES = 90


# ═══════════════════════════════════════════════════════════
# v6/v7/v8/v9 标准化统计量 lazy加载
# ═══════════════════════════════════════════════════════════
def _load_norm_stats(version='v6'):
    """加载指定版本的norm_stats"""
    import json as _json
    p = BASE / 'models' / f'{version}_norm_stats.json'
    if not p.exists():
        return None
    try:
        return _json.loads(p.read_text())
    except:
        return None


# ═══════════════════════════════════════════════════════════
# 预加载指数缓存（模块级，避免每只股票重复查询）
# ═══════════════════════════════════════════════════════════
_INDEX_CACHE = {}   # index_code -> np.array(closes)
_INDEX_CACHE_DT = {}


def _load_index_cache(conn):
    """一次性加载所有基准指数120天收盘价"""
    global _INDEX_CACHE, _INDEX_CACHE_DT
    index_codes = ['000001', '399001', '399006', '000688', '000905', '399852']
    try:
        for ic in index_codes:
            rows = conn.execute(f"""
                SELECT date, close FROM index_daily
                WHERE index_code='{ic}' ORDER BY date DESC LIMIT 120
            """).fetchall()
            if rows and len(rows) >= 60:
                closes = [float(r[1]) for r in rows][::-1]
                dates = [str(r[0])[:10] for r in rows][::-1]
                _INDEX_CACHE[ic] = np.array(closes)
                _INDEX_CACHE_DT[ic] = dates
    except Exception as e:
        print(f"  ⚠️ 指数缓存加载失败: {e}")


def _get_index_for_code(code):
    """根据股票代码返回对应基准指数代码"""
    if code.startswith('688'):
        return '000688'  # 科创50
    elif code.startswith(('30', '301')):
        return '399006'  # 创业板指
    elif code.startswith('002'):
        return '000905'  # 中证500（中小盘）
    elif code.startswith('00'):
        return '399001'  # 深证成指
    elif code.startswith(('8', '4', '920')):
        return '399852'  # 中证1000（小盘/北交所）
    else:
        return '000001'  # 上证指数（主板）


def _get_index_closes(conn, index_code='000001', n=120):
    """查询指定指数最新n个交易日的收盘价 — 优先用内存缓存"""
    if index_code in _INDEX_CACHE:
        return _INDEX_CACHE[index_code], _INDEX_CACHE_DT.get(index_code)
    try:
        rows = conn.execute(f"""
            SELECT date, close FROM index_daily
            WHERE index_code='{index_code}' ORDER BY date DESC LIMIT {n}
        """).fetchall()
        if rows and len(rows) >= 60:
            closes = np.array([float(r[1]) for r in rows][::-1])
            dates = [str(r[0])[:10] for r in rows][::-1]
            _INDEX_CACHE[index_code] = closes
            _INDEX_CACHE_DT[index_code] = dates
            return closes, dates
    except: pass
    return None, None


# ═══════════════════════════════════════════════════════════
# stk_factor 因子加载缓存（模块级）
# ═══════════════════════════════════════════════════════════
_STK_CACHE = {}   # (ts_code, trade_date) -> extra_dict


def _load_stk_factor(conn, ts_code, trade_date):
    """从stk_factor表加载技术指标因子，带缓存"""
    cache_key = (ts_code, trade_date)
    if cache_key in _STK_CACHE:
        return _STK_CACHE[cache_key]

    extra_dict = {}
    try:
        # 先查直接列（MACD/KDJ/RSI/BOLL/CCI）
        direct_cols = ['macd_dif', 'macd_dea', 'macd', 'kdj_k', 'kdj_d', 'kdj_j',
                       'rsi_6', 'rsi_12', 'rsi_24', 'boll_upper', 'boll_mid', 'boll_lower', 'cci']
        direct_vals = conn.execute(f"""
            SELECT {','.join(direct_cols)} FROM stk_factor
            WHERE ts_code='{ts_code}' AND trade_date='{trade_date}'
        """).fetchone()

        if direct_vals:
            for col, val in zip(direct_cols, direct_vals):
                if val is not None and not np.isnan(val):
                    extra_dict[f'{col}_bfq'] = float(val)

        # 再查extra JSON（250个因子）
        extra_str = conn.execute(f"""
            SELECT extra FROM stk_factor
            WHERE ts_code='{ts_code}' AND trade_date='{trade_date}'
        """).fetchone()

        if extra_str and extra_str[0]:
            try:
                ed = json.loads(extra_str[0])
                for k, v in ed.items():
                    if isinstance(v, (int, float)) and not np.isnan(v):
                        # 只保留bfq（前复权）因子，去掉其他复权方式
                        if '_bfq' in k:
                            extra_dict[k] = float(v)
            except: pass

        _STK_CACHE[cache_key] = extra_dict
        return extra_dict

    except Exception as e:
        _STK_CACHE[cache_key] = {}
        return {}


# ═══════════════════════════════════════════════════════════
# 核心特征计算函数
# ═══════════════════════════════════════════════════════════

def compute_raw_features(code, rows, conn, val_entry: dict = None):
    """计算93个原始特征（26 L1 + 40 L2 + 15 L3 + 12 L4）

    Args:
        code: 股票代码 (如 '000001')
        rows: DB查询结果（时间降序），每行 (date, close, open, high, low, change_pct, volume, amount)
        conn: DuckDB连接（用于查询stk_factor/估值/资金数据）
        val_entry: 可选，当日估值字典。不传则从DB查。

    Returns:
        (base_raw, dt_str) — 原始特征数组(93,) 和 最新日期字符串
        或 (None, None) 当数据不足
    """
    if len(rows) < 120:
        return None, None

    try:
        # DB查询为 ORDER BY date DESC（最新在前），统一反转成时间升序
        rows_rev = rows[::-1]
        closes = [float(r[1]) for r in rows_rev]  # r[1] = close
        c = np.array(closes)
        lc = c[-1]

        dates = [str(r[0])[:10] for r in rows_rev]
        dt_str = dates[-1]
        latest_code = f"{code}.SH" if code.startswith(('6', '68', '9')) else f"{code}.SZ"

        # ═══════════════════════════════════════════
        # L1: 量价基础 (26维) — 保持原有逻辑不变
        # ═══════════════════════════════════════════
        chg5 = lc/c[-5]-1 if c[-5] > 0 else 0
        chg10 = lc/c[-10]-1 if c[-10] > 0 else 0
        chg20 = lc/c[-20]-1 if c[-20] > 0 else 0
        chg60 = lc/c[-60]-1 if c[-60] > 0 else 0
        chg120 = lc/c[0]-1

        ma5 = np.mean(c[-5:])
        ma10 = np.mean(c[-10:])
        ma20 = np.mean(c[-20:])
        ma60 = np.mean(c[-60:])

        d5 = lc/ma5-1 if ma5 > 0 else 0
        d10 = lc/ma10-1 if ma10 > 0 else 0
        d20 = lc/ma20-1 if ma20 > 0 else 0
        d60 = lc/ma60-1 if ma60 > 0 else 0
        d120 = lc/np.mean(c)-1

        b1 = 1 if ma5 > ma10 > ma20 else 0
        b2 = 1 if ma20 > ma60 else 0

        price_range = np.max(c[-20:]) - np.min(c[-20:])
        min_20 = np.min(c[-20:])
        rr = price_range / min_20 * 100 if min_20 > 0 else 0

        std20 = np.std(c[-20:]) / np.mean(c[-20:]) * 100

        vols = np.array([float(r[6]) for r in rows_rev[-20:]])
        vr = vols[-1] / np.mean(vols) if np.mean(vols) > 0 else 1

        rl, rh = np.min(c[-20:]), np.max(c[-20:])
        pos = (lc - rl) / (rh - rl) * 100 if rh != rl else 50

        nh = 1 if lc > rh * 0.97 else 0
        vpc = 1 if chg5 > 0 and vr > 1.2 else 0

        c1d = float(rows_rev[-1][5]) / 100.0 if rows_rev[-1][5] is not None else 0
        c3d = lc / c[-3] - 1 if len(c) >= 3 and c[-3] > 0 else 0

        # 估值数据（缺省值用行业均值填充）
        ep = bp = ln_cap = None
        if val_entry is not None:
            ep = val_entry.get('ep')
            bp = val_entry.get('bp')
            ln_cap = val_entry.get('ln_cap')
        else:
            tushare_conn = get_tushare_db()
            ts_code = f"{code}.SH" if code.startswith(('6', '68', '9')) else f"{code}.SZ"
            vr_ = tushare_conn.execute(
                f"SELECT pe_ttm, pb, total_mv FROM daily_basic WHERE ts_code='{ts_code}' ORDER BY trade_date DESC LIMIT 1"
            ).fetchone()
            tushare_conn.close()
            if vr_:
                if vr_[0] and vr_[0] > 0: ep = 1.0 / vr_[0]
                if vr_[1] and vr_[1] > 0: bp = 1.0 / vr_[1]
                if vr_[2] and vr_[2] > 0: ln_cap = np.log(vr_[2])
        if ep is None: ep = 0.5
        if bp is None: bp = 0.5
        if ln_cap is None: ln_cap = 22.0

        # 超额收益（相对基准指数）
        idx_code = _get_index_for_code(code)
        idx_closes, _ = _get_index_closes(conn, idx_code)
        if idx_closes is not None and len(idx_closes) >= 20:
            ex5 = chg5 - (idx_closes[-1]/idx_closes[-5]-1) if idx_closes[-5] > 0 else 0
            ex10 = chg10 - (idx_closes[-1]/idx_closes[-10]-1) if idx_closes[-10] > 0 else 0
            ex20 = chg20 - (idx_closes[-1]/idx_closes[-20]-1) if idx_closes[-20] > 0 else 0
        else:
            ex5 = ex10 = ex20 = 0.0

        # ── L1衍生特征（偏度/峰度等）──
        window20 = c[-20:]
        skew20 = float(skew(window20)) if len(window20) >= 20 else 0
        kurt20 = float(kurtosis(window20, fisher=False)) if len(window20) >= 20 else 3

        pcts_rev = np.array([float(r[5] or 0) for r in rows_rev])
        signs20 = np.sign(pcts_rev[-20:])
        dn_streak = sum(1 for s in reversed(signs20) if s < 0)
        up_ratio10 = np.sum(signs20[-10:] > 0) / 10.0

        vol_old = float(np.std(pcts_rev[-60:-20]) * math.sqrt(252)) if len(pcts_rev) >= 60 else 0
        vol_new = float(np.std(pcts_rev[-20:]) * math.sqrt(252))
        vol_chg = vol_new / vol_old - 1 if vol_old > 0 else 0

        rel_str = chg5 - (ma20 / ma60 - 1) if ma60 > 0 else 0
        kurt60 = float(kurtosis(c[-60:], fisher=False)) if len(c) >= 60 else 3

        x5 = np.arange(5); y5 = c[-5:]
        slope5 = float(np.sum((x5-x5.mean())*(y5-y5.mean()))/np.sum((x5-x5.mean())**2)) if np.sum((x5-x5.mean())**2) > 0 else 0
        x10 = np.arange(10); y10 = c[-10:]
        slope10 = float(np.sum((x10-x10.mean())*(y10-y10.mean()))/np.sum((x10-x10.mean())**2)) if np.sum((x10-x10.mean())**2) > 0 else 0
        accel = slope5 - slope10

        vols_20 = np.array([float(r[6] or 0) for r in rows_rev[-20:]])
        vr_20 = vols_20[-1] / np.mean(vols_20) if np.mean(vols_20) > 0 else 1.0
        vp_shrink = 1.0 if chg5 < -0.01 and vr_20 < 0.7 else 0.0
        vp_div = 1.0 if (chg5 > 0 and vr_20 < 0.8) or (chg5 < 0 and vr_20 > 1.2) else 0.0

        # ═══════════════════════════════════════════
        # L2: stk_factor技术指标 (40维)
        # ═══════════════════════════════════════════
        extra = _load_stk_factor(conn, latest_code, dt_str.replace('-', ''))

        def ef(key, default=0.0):
            """从extra字典安全取值"""
            return extra.get(key, default)

        # MACD系 (6)
        macd_dif_bfq = ef('macd_dif_bfq', 0.0)
        macd_dea_bfq = ef('macd_dea_bfq', 0.0)
        macd_bfq = ef('macd_bfq', 0.0)
        macd_hist_bfq = macd_dif_bfq - macd_dea_bfq if macd_dif_bfq or macd_dea_bfq else ef('macd_bfq', 0.0)
        macd_dif_hfq = ef('macd_dif_hfq', 0.0)
        macd_dif_qfq = ef('macd_dif_qfq', 0.0)

        # KDJ系 (6)
        kdj_k_bfq = ef('kdj_k_bfq', 50.0)
        kdj_d_bfq = ef('kdj_d_bfq', 50.0)
        kdj_j_bfq = ef('kdj_j_bfq', 50.0)
        kdk_ratio_bfq = (kdj_k_bfq / kdj_d_bfq - 1) if kdj_d_bfq > 0 else 0
        # KDJ金叉/死叉判断（用前一天）
        prev_extra = _load_stk_factor(conn, latest_code, dates[-2].replace('-', '')) if len(dates) >= 2 else {}
        prev_kdj_k = prev_extra.get('kdj_k_bfq', kdj_k_bfq)
        prev_kdj_d = prev_extra.get('kdj_d_bfq', kdj_d_bfq)
        kdk_prev = prev_kdj_k - prev_kdj_d if prev_kdj_k and prev_kdj_d else 0
        kdk_curr = kdj_k_bfq - kdj_d_bfq
        kdj_cross_up = 1.0 if kdk_prev <= 0 and kdk_curr > 0 else 0.0
        kdj_cross_down = 1.0 if kdk_prev >= 0 and kdk_curr < 0 else 0.0

        # RSI系 (6)
        rsi_6_bfq = ef('rsi_6_bfq', 50.0)
        rsi_12_bfq = ef('rsi_12_bfq', 50.0)
        rsi_24_bfq = ef('rsi_24_bfq', 50.0)
        rsi_divergence_bfq = abs(rsi_6_bfq - rsi_12_bfq) / (rsi_12_bfq + 1e-8)
        rsi_ma5_bfq = np.mean([ef(f'rsi_6_bfq', 50.0), ef('rsi_6_bfq', 50.0)])  # placeholder
        rsi_level_bull = 1.0 if rsi_6_bfq > 70 else (0.0 if rsi_6_bfq < 30 else 0.5)

        # BOLL系 (6)
        boll_upper_bfq = ef('boll_upper_bfq', lc)
        boll_mid_bfq = ef('boll_mid_bfq', lc)
        boll_lower_bfq = ef('boll_lower_bfq', lc)
        boll_width_bfq = (boll_upper_bfq - boll_lower_bfq) / boll_mid_bfq if boll_mid_bfq > 0 else 0
        price_boll_pos = (lc - boll_lower_bfq) / (boll_upper_bfq - boll_lower_bfq) if (boll_upper_bfq - boll_lower_bfq) > 0 else 0.5
        boll_break_up = 1.0 if lc > boll_upper_bfq else 0.0

        # 趋势/动量 (8)
        cci_bfq = ef('cci_bfq', 0.0)
        roc_10_bfq = ef('roc_bfq', 0.0)  # Tushare的ROC默认周期可能不同，取最接近的
        mtm_10_bfq = ef('mtm_bfq', 0.0)
        wr_6_bfq = ef('wr_bfq', -50.0)
        dmi_pdi_bfq = ef('dmi_pdi_bfq', 20.0)
        dmi_mdi_bfq = ef('dmi_mdi_bfq', 20.0)
        dmi_adx_bfq = ef('dmi_adx_bfq', 25.0)

        # 均线系 (4) — stk_factor直接列有ma_bfq_*
        ma5_stk = ef('ma_bfq_5', ma5)
        ma20_stk = ef('ma_bfq_20', ma20)
        ma60_stk = ef('ma_bfq_60', ma60)
        ma_ratio_short_long = ma5_stk / ma60_stk - 1 if ma60_stk > 0 else 0

        # 量价衍生 (4)
        obv_bfq = ef('obv_bfq', 0.0)
        turnover_rate_bfq = ef('turnover_rate', 0.0)  # stk_factor直接列有volume_ratio
        volume_ratio_f = ef('volume_ratio', 1.0)

        # ═══════════════════════════════════════════
        # L3: 估值质量 (15维) — 从daily_basic + stock_valuation
        # ═══════════════════════════════════════════
        try:
            t_conn = get_tushare_db()

            # daily_basic: pe_ttm, pb, total_mv, turnover_rate_f等
            db_row = t_conn.execute(f"""
                SELECT pe_ttm, pb, ps, pcf_fcfttm, dividend_ratio, total_mv, circ_mv,
                       turnover_rate_f, volume_ratio
                FROM daily_basic
                WHERE ts_code='{latest_code}' ORDER BY trade_date DESC LIMIT 1
            """).fetchone()

            if db_row:
                pe_ttm = float(db_row[0]) if db_row[0] and db_row[0] > 0 else 50.0
                pb_val = float(db_row[1]) if db_row[1] and db_row[1] > 0 else 3.0
                ps_val = float(db_row[2]) if db_row[2] and db_row[2] > 0 else 5.0
                pcf_val = float(db_row[3]) if db_row[3] and db_row[3] > 0 else 20.0
                div_yield = float(db_row[4]) if db_row[4] and db_row[4] >= 0 else 0.0
                total_mv_val = float(db_row[5]) if db_row[5] and db_row[5] > 0 else 1e10
                circ_mv_val = float(db_row[6]) if db_row[6] and db_row[6] > 0 else total_mv_val
                turnover_f = float(db_row[7]) if db_row[7] is not None else 0.0
                vol_rat_qfq = float(db_row[8]) if db_row[8] and db_row[8] > 0 else 1.0
            else:
                pe_ttm, pb_val, ps_val, pcf_val = 50.0, 3.0, 5.0, 20.0
                div_yield, total_mv_val, circ_mv_val = 0.0, 1e10, 1e10
                turnover_f, vol_rat_qfq = 0.0, 1.0

            t_conn.close()
        except:
            pe_ttm, pb_val, ps_val, pcf_val = 50.0, 3.0, 5.0, 20.0
            div_yield, total_mv_val, circ_mv_val = 0.0, 1e10, 1e10
            turnover_f, vol_rat_qfq = 0.0, 1.0

        mv_ratio = circ_mv_val / total_mv_val if total_mv_val > 0 else 1.0
        ln_total_mv = np.log(total_mv_val) if total_mv_val > 0 else 23.0

        # Amihud流动性指标（用过去20日日均）
        amihud = 0.0
        if len(rows_rev) >= 20:
            daily_returns = []
            for i in range(-20, 0):
                r_i = abs(float(c[i]) / c[i-1] - 1) if c[i-1] > 0 else 0
                v_i = float(rows_rev[i][6]) if rows_rev[i][6] is not None else 0
                if v_i > 0 and r_i >= 0:
                    daily_returns.append(r_i / (v_i / 1e8))  # 转换为百万成交额
            amihud = np.mean(daily_returns) if daily_returns else 0.0

        # Beta（相对基准指数20日）
        beta_20d = 0.0
        idx_closes_local, _ = _get_index_closes(conn, idx_code)
        if idx_closes_local is not None and len(idx_closes_local) >= 20:
            stock_ret = np.diff(c[-20:]) / c[-21:-1]
            market_ret = np.diff(idx_closes_local[-20:]) / idx_closes_local[-21:-1]
            min_len = min(len(stock_ret), len(market_ret))
            if min_len >= 10:
                cov = np.cov(stock_ret[:min_len], market_ret[:min_len])[0, 1]
                var_m = np.var(market_ret[:min_len])
                beta_20d = cov / var_m if var_m > 0 else 0.0

        # 52周高低点距离（用60日代替）
        high_60d = np.max(c[-60:]) if len(c) >= 60 else lc
        low_60d = np.min(c[-60:]) if len(c) >= 60 else lc
        high_low_avg = (high_60d + low_60d) / 2 / lc - 1

        # 价格60日排名
        price_rank_60d = np.sum(c[-60:] < lc) / 60.0 if len(c) >= 60 else 0.5

        # ═══════════════════════════════════════════
        # L4: 资金+财务 (12维) — money_flow + fin_income
        # ═══════════════════════════════════════════
        try:
            mf_row = t_conn.execute(f"""
                SELECT money_mainflow, money_superbig, money_big,
                       money_small, money_mid, ts_code
                FROM money_flow
                WHERE ts_code='{code}' AND date='{dt_str[:10]}'
            """).fetchone() if 't_conn' in dir() else None

            # 重新查（上面可能没定义）
            mf_row = get_tushare_db().execute(f"""
                SELECT main_net_flow, super_large_net_flow, large_net_flow,
                       mid_net_flow, small_net_flow
                FROM money_flow
                WHERE ts_code='{code}' AND date='{dt_str[:10]}'
            """).fetchone()

            if mf_row:
                main_net = float(mf_row[0]) if mf_row[0] else 0.0
                super_large = float(mf_row[1]) if mf_row[1] else 0.0
                total_flow = sum(float(x or 0) for x in mf_row[:5])
                money_net_flow_pct = main_net / abs(total_flow) * 100 if total_flow != 0 else 0.0
                money_main_inflow = main_net
                money_super_large = super_large
            else:
                money_net_flow_pct = money_main_inflow = money_super_large = 0.0

            # 财务数据（最近一期季报）
            fi_row = get_tushare_db().execute(f"""
                SELECT roe, current_ratio, debt_to_assets,
                       gross_profit_margin, net_profit_margin,
                       revenue_yoy, np_parent_net_profit_yoy,
                       eps_yoy
                FROM fina_indicator
                WHERE ts_code='{latest_code}' ORDER BY end_date DESC LIMIT 1
            """).fetchone()

            if fi_row:
                roe_ttm = float(fi_row[0]) if fi_row[0] else 0.0
                current_ratio_val = float(fi_row[1]) if fi_row[1] and fi_row[1] > 0 else 2.0
                debt_asset_ratio = float(fi_row[2]) if fi_row[2] is not None else 0.5
                gross_margin = float(fi_row[3]) / 100 if fi_row[3] is not None else 0.3
                net_margin = float(fi_row[4]) / 100 if fi_row[4] is not None else 0.1
                revenue_yoy_val = float(fi_row[5]) if fi_row[5] is not None else 0.0
                profit_yoy_val = float(fi_row[6]) if fi_row[6] is not None else 0.0
                eps_growth_1y_val = float(fi_row[7]) if fi_row[7] is not None else 0.0
            else:
                roe_ttm = current_ratio_val = debt_asset_ratio = gross_margin = net_margin = revenue_yoy_val = profit_yoy_val = eps_growth_1y_val = 0.0

        except:
            money_net_flow_pct = money_main_inflow = money_super_large = 0.0
            roe_ttm = current_ratio_val = debt_asset_ratio = gross_margin = net_margin = revenue_yoy_val = profit_yoy_val = eps_growth_1y_val = 0.0

        # ═══════════════════════════════════════════
        # 组装93维特征向量
        # ═══════════════════════════════════════════
        base_raw = np.array([
            # L1: 量价基础 (26)
            chg5, chg10, chg20, chg60, chg120,
            d5, d10, d20, d60, d120,
            b1, b2, rr, std20, vr, pos,
            nh, vpc, c1d, c3d, ep, bp, ln_cap,
            ex5, ex10, ex20,

            # L2: stk_factor技术指标 (40)
            macd_dif_bfq, macd_dea_bfq, macd_bfq, macd_hist_bfq, macd_dif_hfq, macd_dif_qfq,
            kdj_k_bfq, kdj_d_bfq, kdj_j_bfq, kdk_ratio_bfq, kdj_cross_up, kdj_cross_down,
            rsi_6_bfq, rsi_12_bfq, rsi_24_bfq, rsi_divergence_bfq, rsi_ma5_bfq, rsi_level_bull,
            boll_upper_bfq, boll_mid_bfq, boll_lower_bfq, boll_width_bfq, price_boll_pos, boll_break_up,
            cci_bfq, roc_10_bfq, mtm_10_bfq, wr_6_bfq, dmi_pdi_bfq, dmi_mdi_bfq, dmi_adx_bfq,
            ma5_stk, ma20_stk, ma60_stk, ma_ratio_short_long,
            obv_bfq, volume_ratio_f, turnover_rate_bfq,

            # L3: 估值质量 (15)
            pe_ttm, pb_val, ps_val, pcf_val,
            div_yield, ln_total_mv, circ_mv_val, mv_ratio,
            turnover_f, vol_rat_qfq, amihud, beta_20d,
            high_low_avg, price_rank_60d,

            # L4: 资金+财务 (12)
            money_net_flow_pct, money_main_inflow, money_super_large,
            revenue_yoy_val, profit_yoy_val, roe_ttm,
            current_ratio_val, debt_asset_ratio, gross_margin, net_margin,
            revenue_yoy_val, eps_growth_1y_val,
        ], dtype=np.float64)

        return base_raw, dt_str

    except Exception:
        import traceback
        traceback.print_exc()
        return None, None


def standardize_v5(features):
    """用v6统计量标准化特征（用于20d模型）

    Args:
        features: 原始特征数组 (93,) 或 (N, 93)

    Returns:
        标准化后的特征数组
    """
    stats = _load_norm_stats('v6') or _load_norm_stats('v8') or _load_norm_stats('v10')
    if stats is None:
        return features

    one_dim = len(features.shape) == 1
    if one_dim:
        features = features.reshape(1, -1)

    result = features.copy()
    for j in range(min(len(FEAT_NAMES), result.shape[1])):
        key = f'feat_{j}'
        if key in stats:
            s = stats[key]
            if s['std'] > 0:
                lo = s['low']
                hi = s['high']
                result[:, j] = np.clip(result[:, j], lo, hi)
                result[:, j] = (result[:, j] - s['mean']) / s['std']

    return result.flatten() if one_dim else result


def standardize_v9(features, stats):
    """用v9统计量标准化特征（用于40d模型）"""
    feat = features.copy()
    for j in range(min(26, len(feat))):
        key = f'feat_{j}'
        if key in stats:
            s = stats[key]
            if s['std'] > 0:
                feat[j] = max(feat[j], s['low'])
                feat[j] = min(feat[j], s['high'])
                feat[j] = (feat[j] - s['mean']) / s['std']
    return feat
