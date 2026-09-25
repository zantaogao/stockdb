"""
v8 单一模型评分 — 独立于features.py的推理管线
特征集（21维）：ep, bp, ln_cap, roe, chg20, chg60, chg20_resid, d20, d60, pos20, std20, vr, vol_chg, rel_str, c1d, dn_streak, up_ratio10 + 4GTJA
"""
import numpy as np
import lightgbm as lgb
import duckdb
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
MODEL_DIR = BASE / 'models'

_V8_MODEL = None
_V8_STATS = {}


def _ensure_v8():
    global _V8_MODEL, _V8_STATS
    if _V8_MODEL is not None:
        return
    
    model_path = MODEL_DIR / 'lgb_reg_v8.txt'
    stats_path = MODEL_DIR / 'norm_stats_v8.json'
    
    if model_path.exists():
        _V8_MODEL = lgb.Booster(model_file=str(model_path))
    
    if stats_path.exists():
        import json
        with open(stats_path) as f:
            _V8_STATS = json.load(f)


def compute_v8_features(closes, volumes, val_dict):
    """计算v8的21维特征（不含GTJA）"""
    n = len(closes)
    if n < 120:
        return None
    
    lc = closes[-1]
    
    # ── 基本面 (4) ──
    ep = val_dict.get('ep', 0.5)
    bp = val_dict.get('bp', 0.5)
    ln_cap = val_dict.get('ln_cap', 22.0)
    roe = val_dict.get('roe', None)
    if roe is None or roe <= 0:
        roe = 0.3
    
    # ── 动量 (3) ──
    chg20 = lc / closes[-21] - 1 if n >= 21 else 0
    chg60 = lc / closes[-61] - 1 if n >= 61 else 0
    
    # chg20对chg60的残差
    resid = chg20
    if n >= 180:
        c_w = closes[-120:]
        cg20_all, cg60_all = [], []
        for i in range(21, len(c_w)):
            cg20_all.append(c_w[i] / c_w[max(0, i-21)] - 1)
            cg60_all.append(c_w[i] / c_w[max(0, i-61)] - 1)
        if len(cg20_all) >= 30:
            x = np.array(cg60_all)
            y = np.array(cg20_all)
            mx, my = np.mean(x), np.mean(y)
            ss_xy = np.sum((x - mx) * (y - my))
            ss_xx = np.sum((x - mx)**2)
            if abs(ss_xx) > 1e-15:
                beta = ss_xy / ss_xx
                resid = chg20 - beta * chg60
    
    # ── 偏离度 (3) ──
    ma20 = np.mean(closes[-20:]) if n >= 20 else lc
    ma60 = np.mean(closes[-60:]) if n >= 60 else lc
    d20 = lc / ma20 - 1 if ma20 > 0 else 0
    d60 = lc / ma60 - 1 if ma60 > 0 else 0
    
    if n >= 20:
        c20 = closes[-20:]
        lo20, hi20 = min(c20), max(c20)
        pos20 = (lc - lo20) / (hi20 - lo20 + 1e-15) if hi20 > lo20 else 0.5
    else:
        pos20 = 0.5
    
    # ── 波动/量价 (4) ──
    std20 = np.std(closes[-20:]) / np.mean(closes[-20:]) * 100 if n >= 20 else 0
    
    vols_20 = volumes[-20:] if n >= 20 else [volumes[-1]]
    vr = volumes[-1] / (np.mean(vols_20) + 1e-15) if len(vols_20) > 0 and np.mean(vols_20) > 0 else 1.0
    
    if n >= 15:
        vol_recent = np.mean(volumes[-5:])
        vol_early = np.mean(volumes[-15:-5])
        vol_chg = vol_recent / (vol_early + 1e-15) - 1 if vol_early > 0 else 0
    else:
        vol_chg = 0
    
    # rel_str: stock 5d return vs long-term trend
    if n >= 6:
        stock_ret_5d = np.prod([1 + closes[-i]/closes[-(i+1)] - 1 for i in range(1, 6)]) - 1
        lt_trend = (lc / closes[-61] - 1) * (5/60) if n >= 61 else 0
        rel_str = stock_ret_5d - lt_trend
    else:
        rel_str = 0
    
    # ── 形态 (3) ──
    c1d = lc / closes[-2] - 1 if n >= 2 and closes[-2] > 0 else 0
    
    dn_streak = 0
    for i in range(len(closes)-1, max(-1, len(closes)-20), -1):
        prev_c = closes[i-1] if i > 0 else lc
        ret_i = (closes[i] / prev_c - 1) if prev_c > 0 else 0
        if ret_i < 0:
            dn_streak += 1
        else:
            break
    
    if n >= 10:
        up_ratio10 = sum(1 for i in range(max(0, len(closes)-10), len(closes)) 
                        if (closes[i] / closes[max(0,i-1)] - 1) > 0) / 10.0
    else:
        up_ratio10 = 0.5
    
    return [ep, bp, ln_cap, roe, chg20, chg60, resid,
            d20, d60, pos20, std20, vr, vol_chg, rel_str,
            c1d, dn_streak, up_ratio10]


def standardize_v8_features(feat_vec):
    """用v8的norm_stats标准化特征"""
    if not _V8_STATS:
        return np.array(feat_vec)
    
    result = []
    for j, val in enumerate(feat_vec):
        key = f'feat_{j}'
        if key in _V8_STATS:
            s = _V8_STATS[key]
            if s['std'] > 1e-10:
                lo, hi = s['low'], s['high']
                val = max(val, lo) if not np.isnan(lo) else val
                val = min(val, hi) if not np.isnan(hi) else val
                val = (val - s['mean']) / s['std']
        result.append(float(val))
    
    return np.array(result, dtype=np.float32)


def score_v8(code, rows, conn=None):
    """用v8模型评分单只股票
    
    Args:
        code: 股票代码
        rows: DB查询结果 (date, close, open, high, low, change_pct, volume, amount) ORDER BY date DESC
        conn: DuckDB连接（用于查估值和GTJA）
    
    Returns:
        dict with 'v8_score' (raw model output in %), or None if insufficient data
    """
    _ensure_v8()
    if _V8_MODEL is None or len(rows) < 120:
        return None
    
    # Convert rows to arrays (DB returns DESC, reverse to ASC for computation)
    rows_rev = rows[::-1]
    closes = np.array([float(r[1]) for r in rows_rev], dtype=np.float64)
    volumes = np.array([float(r[6]) if r[6] else 0 for r in rows_rev], dtype=np.float64)
    
    # Get valuation data from tushare.db daily_basic
    from core.db import get_db as get_db_conn, TUSHARE_DB_PATH
    conn_local = conn or get_db_conn()
    
    ts_code = f"{code}.SH" if code.startswith(('6', '68', '9')) else f"{code}.SZ"
    tushare_conn = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)
    vr_ = tushare_conn.execute(
        f"SELECT pe_ttm, pb, total_mv FROM daily_basic WHERE ts_code='{ts_code}' ORDER BY trade_date DESC LIMIT 1"
    ).fetchone()
    
    val_dict = {}
    if vr_:
        if vr_[0] and float(vr_[0]) > 0:
            try:
                val_dict['ep'] = 1.0 / float(vr_[0])
            except (ValueError, ZeroDivisionError):
                pass
        if vr_[1] and float(vr_[1]) > 0:
            try:
                val_dict['bp'] = 1.0 / float(vr_[1])
            except (ValueError, ZeroDivisionError):
                pass
        if vr_[2] and float(vr_[2]) > 0:
            try:
                val_dict['ln_cap'] = np.log(float(vr_[2]))
            except (ValueError, OverflowError):
                pass
    
    # Get ROE from financial data (从 tushare.db fina_indicator — 2026-08-01 改: fin_income重建为API完整版后无roe列, roe在fina_indicator)
    # 注意: fina_indicator.roe 有空字符串''，需用 TRY_CAST 过滤
    roe_rows = tushare_conn.execute(
        f"SELECT end_date, roe FROM fina_indicator WHERE ts_code='{ts_code}' AND TRY_CAST(roe AS DOUBLE) IS NOT NULL ORDER BY end_date DESC LIMIT 1"
    ).fetchall()
    
    if roe_rows:
        for dt, rv in roe_rows:
            try:
                rv_val = float(rv)
                if rv_val > 0:
                    # Find all valuation dates >= this ROE date and set roe
                    val_dates = tushare_conn.execute(
                        f"SELECT DISTINCT trade_date FROM daily_basic WHERE ts_code='{ts_code}' ORDER BY trade_date DESC"
                    ).fetchall()
                    for vd in val_dates[:5]:  # Just check first few
                        v_key = (code, str(vd[0]).replace('-', '')[:8])
            except:
                pass
    
    tushare_conn.close()

    # Compute features
    feat_vec = compute_v8_features(closes, volumes, val_dict)
    if feat_vec is None:
        return None
    
    # Standardize
    feat_normed = standardize_v8_features(feat_vec)
    
    # Get GTJA values (reuse existing logic from scoring.py)
    from core.features import get_gtja_signals, _build_gtja_date_index
    import gzip, pickle
    
    pkl_path = BASE / 'gtja_signals.pkl.gz'
    gtja_data = None
    if pkl_path.exists():
        try:
            with gzip.open(str(pkl_path), 'rb') as f:
                gtja_data = pickle.load(f)
        except:
            pass
    
    dt_str = str(rows_rev[-1][0])[:10]
    
    # Build GTJA date index if needed
    _build_gtja_date_index(gtja_data)
    
    # Get only the 4 GTJA factors used by v8
    gtja_all = ['gtja_006', 'gtja_083', 'gtja_177', 'gtja_184']
    all_gtja = get_gtja_signals(code, dt_str, gtja_data) if gtja_data else []
    gtja_v8 = all_gtja[:4]  # Only first 4
    
    # Combine and pad to 21 dims
    all_feats = np.array(feat_vec + gtja_v8, dtype=np.float32)
    
    # Standardize ALL features (including GTJA) using v8 stats
    feat_final = standardize_v8_features(list(all_feats))
    
    # Pad to 21 if needed
    while len(feat_final) < 21:
        feat_final = np.append(feat_final, 0.0)
    
    pred = _V8_MODEL.predict(feat_final.reshape(1, -1))[0]
    
    return {
        'v8_score': round(float(pred) * 100, 1),
        'v8_raw': float(pred),
    }
