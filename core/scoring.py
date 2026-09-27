"""
统一评分 v12 — reg10×20% + reg20×30% + reg40×50%（2026-08-03 权重回测调整）
signal_agent.py 通过此模块计算全市场评分
"""
import json
import os
import sys
import numpy as np
import lightgbm as lgb
from pathlib import Path
import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

BASE = Path.home() / '.hermes' / 'stockdb'
MODEL_DIR = BASE / 'models'
TUSHARE_DB = BASE / 'tushare.db'


def _safe_connect(read_only=True):
    """安全连接：走 core/db.py 统一入口，带 WAL 损坏自动恢复"""
    from core.db import get_tushare_db
    return get_tushare_db(read_only)

# 模型路径
REG10_MODEL_PATH = MODEL_DIR / 'lgb_reg_10d_v8.txt'   # 0927 v8重训(2019起样本, 31维PV_INDICES同口径)
REG10_STATS_PATH = MODEL_DIR / 'v10_v8_stats.json'
REG20_MODEL_PATH = MODEL_DIR / 'lgb_reg_20d_v2.txt'   # 0926重训(带真值ex); 旧mac_v1验证段IC-0.07已退役 models/retired_20260926/
REG20_STATS_PATH = MODEL_DIR / 'v20_v2_stats.json'
REG40_MODEL_PATH = MODEL_DIR / 'lgb_reg_40d_v8.txt'   # 0927 v8重训(2019起样本, 26维BASE_KEEP+kdj_k/cci/rsi_12=29维)
REG40_STATS_PATH = MODEL_DIR / 'v40_v8_stats.json'

# 特征配置（匹配M2训练脚本）
BASE_KEEP_INDICES = [0,1,2,3,4,5,6,7,8,9,11,12,13,14,15,18,19,20,21,22,23,24,25,26,28,29]
FACTOR_FIELDS = ['kdj_k', 'cci', 'rsi_12']

# ETF 模型配置
ETF_MODEL_PATH = MODEL_DIR / 'lgb_reg_etf_20d_v1.txt'
ETF_STATS_PATH = MODEL_DIR / 'v_etf_v1_stats.json'
ETF_FEAT_NAMES = [
    'chg5','chg10','chg20','chg60',
    'd5','d10','d20','d60',
    'bull1','bull2','rr','std20','vr','pos','nh','vpc',
    'c1d','c3d',
    'skew20','dn_streak','up_ratio10',
    'vol_chg','slope5','accel',
]

# 10d v3 纯量价短期特征索引（从38维原始特征中选择）
PV_INDICES = [
    0,1,2,3,    5,6,7,    10,11,
    12,13,14,15,16,17,  18,19,
    23,24,25,  26,27,  28,29,  30,
    32,33,34,35,  36,37,
]

_models_loaded = False
_reg10_model = None
_reg20_model = None
_reg40_model = None
_stats10 = {}
_stats20 = {}
_stats40 = {}
_idx_data_cache = None
_gtja_cache = {}

# GTJA 因子配置（4个主力因子）
GTJA_4 = ['gtja_006', 'gtja_083', 'gtja_177', 'gtja_184']
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'


def _load_models():
    global _models_loaded, _reg10_model, _reg20_model, _reg40_model, _stats10, _stats20, _stats40
    if _models_loaded:
        return
    if REG10_MODEL_PATH.exists():
        _reg10_model = lgb.Booster(model_file=str(REG10_MODEL_PATH))
        print(f"  [scoring] 10d模型已加载 ({_reg10_model.num_trees()}棵树)")
        if REG10_STATS_PATH.exists():
            with open(REG10_STATS_PATH) as f:
                _stats10 = json.load(f)
    if REG20_MODEL_PATH.exists():
        _reg20_model = lgb.Booster(model_file=str(REG20_MODEL_PATH))
        print(f"  [scoring] 20d模型已加载 ({_reg20_model.num_trees()}棵树)")
        if REG20_STATS_PATH.exists():
            with open(REG20_STATS_PATH) as f:
                _stats20 = json.load(f)
    if REG40_MODEL_PATH.exists():
        _reg40_model = lgb.Booster(model_file=str(REG40_MODEL_PATH))
        print(f"  [scoring] 40d模型已加载 ({_reg40_model.num_trees()}棵树)")
        if REG40_STATS_PATH.exists():
            with open(REG40_STATS_PATH) as f:
                _stats40 = json.load(f)
    _models_loaded = True


def _load_idx_data():
    """加载指数数据缓存"""
    global _idx_data_cache
    if _idx_data_cache is not None:
        return _idx_data_cache
    from feat_tushare import load_index_data
    _idx_data_cache = load_index_data()
    return _idx_data_cache


def _load_gtja():
    """加载 GTJA 数据缓存"""
    global _gtja_cache
    if _gtja_cache:
        return _gtja_cache
    import gzip, pickle
    try:
        if GTJA_PKL.exists():
            with gzip.open(GTJA_PKL, 'rb') as f:
                _gtja_cache = pickle.load(f)
            print(f"  [scoring] GTJA已加载 ({len(_gtja_cache)}因子)")
    except Exception as e:
        print(f"  [scoring] GTJA加载失败: {e}")
    return _gtja_cache


def _compute_gtja_score(code, latest_date_str):
    """计算 GTJA 合成评分（横截面百分位排名）
    返回 0-100 的评分，0表示不可用
    """
    gtja_data = _load_gtja()
    if not gtja_data:
        return 0

    factor_scores = {}
    for gn in GTJA_4:
        if gn not in gtja_data:
            continue
        df = gtja_data[gn]
        # 找最近可用的日期
        available = sorted(df.index)
        best_date = None
        for d in reversed(available):
            ds = str(d)[:10]
            if ds <= latest_date_str:
                best_date = ds
                break
        if best_date is None:
            continue
        row = df.loc[best_date]
        valid = row.dropna()
        if len(valid) < 100:
            continue
        # 横截面排名百分位
        from scipy import stats
        z = (valid - valid.mean()) / valid.std() if valid.std() > 0 else 0
        pcts = stats.rankdata(z) / len(z) * 100
        factor_scores[gn] = {c: float(p) for c, p in zip(valid.index, pcts)}

    if not factor_scores or code not in str(factor_scores):
        return 0

    # 等权合成
    vals = []
    for gn in GTJA_4:
        if gn in factor_scores and code in factor_scores[gn]:
            vals.append(factor_scores[gn][code])

    if not vals:
        return 0

    return round(sum(vals) / len(vals), 1)


def _standardize(feat_vec, stats):
    """标准化特征向量"""
    X = feat_vec.copy().reshape(1, -1)
    n_feats = X.shape[1]
    for j in range(n_feats):
        key = f'feat_{j}'
        if key in stats:
            s = stats[key]
            if s['std'] > 0:
                X[0, j] = np.clip(X[0, j], s['low'], s['high'])
                X[0, j] = (X[0, j] - s['mean']) / s['std']
    return X


def _compute_ml_features(code, conn, as_of_date=None):
    """用 feat_tushare 管道计算29维特征

    Args:
        code: 股票代码，如 '600508'
        conn: DuckDB 连接
        as_of_date: 可选，评估基准日期 'YYYYMMDD'，默认用最新数据
    """
    from feat_tushare import (
        compute_features, get_board_index, apply_forward_adjust,
        get_factor_from_db
    )
    
    # 修复(0926): 北交所(9开头)在 daily 里后缀是 .BJ，旧版硬编码 .SH → 347只北交所票日线0行、从未被打分
    if code.startswith('9'):
        ts_code_full = f"{code}.BJ"
    elif code.startswith(('6', '68')):
        ts_code_full = f"{code}.SH"
    else:
        ts_code_full = f"{code}.SZ"
    
    # 读取日线数据（可按日期过滤）
    date_filter = f"AND trade_date <= '{as_of_date}'" if as_of_date else ''
    rows = conn.execute(f"""
        SELECT trade_date, close, open, high, low, COALESCE(pct_chg,0), vol, amount
        FROM daily WHERE ts_code='{ts_code_full}' {date_filter}
        ORDER BY trade_date DESC LIMIT 200
    """).fetchall()
    if not rows or len(rows) < 120:
        return None
    rows = rows[::-1]  # ascending
    
    closes = [float(r[1]) for r in rows]
    highs_raw = [float(r[3]) for r in rows]
    lows_raw = [float(r[4]) for r in rows]
    pcts = [float(r[5])/100.0 for r in rows]
    volumes = [float(r[6]) for r in rows]
    dates_str = [str(r[0])[:10] for r in rows]
    
    # 复权因子（adj_factor 用 ts_code 格式）
    adj_rows = conn.execute(
        "SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code=? ORDER BY trade_date",
        [ts_code_full]
    ).fetchall()
    adj_closes, adj_highs, adj_lows = apply_forward_adjust(
        closes, highs_raw, lows_raw, adj_rows
    )
    
    # 指数数据
    idx_data = _load_idx_data()
    board_idx = get_board_index(code)
    idx_info = idx_data.get(board_idx)
    idx_closes = None
    if idx_info:
        import bisect
        # 修复(0926): daily.trade_date 无横杠('20260924')，index_daily 日期带横杠('2026-09-24')，
        # 旧版 `dates_str[-1] in idx_info['dict']` 恒 False → ex5/ex10/ex20 生产恒 0。
        # 统一去横杠比较（idx dates 排序不受影响，bisect 目标用同格式切片对齐）。
        _q = dates_str[-1].replace('-', '')
        _dates_nodash = [dd.replace('-', '') for dd in idx_info['dates']]
        ip = bisect.bisect_right(_dates_nodash, _q) - 1
        if ip >= 20:
            idx_closes = {idx_info['dates'][j]: idx_info['dict'][idx_info['dates'][j]] for j in range(ip + 1)}
    
    # 估值 (从 daily_basic 查，用 ts_code 格式；历史回算时按 as_of_date 过滤防未来泄漏)
    val_cond = "AND trade_date <= ?" if as_of_date else ""
    val_params = [ts_code_full] + ([as_of_date] if as_of_date else [])
    val_row = conn.execute(
        f"SELECT pe_ttm, pb, total_mv FROM daily_basic "
        f"WHERE ts_code=? {val_cond} ORDER BY trade_date DESC LIMIT 1", val_params
    ).fetchone()
    val_dict = {}
    if val_row:
        pe, pb, mv = val_row
        if pe and float(pe) > 0: val_dict['ep'] = 1.0 / float(pe)
        if pb and float(pb) > 0: val_dict['bp'] = 1.0 / float(pb)
        if mv and float(mv) > 0: val_dict['ln_cap'] = np.log(float(mv))
    
    # 30基础特征（0927: 传个股日期序列, ex5/10/20 新口径按个股日历回看）
    feat = compute_features(adj_closes, adj_highs, adj_lows, volumes, pcts, idx_closes, val_dict, dates=dates_str)
    
    # 选择26个基础特征
    feat_selected = np.array([feat[i] for i in BASE_KEEP_INDICES], dtype=np.float64)
    
    # stk_factor 因子
    dt_clean = dates_str[-1].replace('-', '')
    fv = get_factor_from_db(code, dt_clean, FACTOR_FIELDS, conn)
    factor_vals = [float(fv.get(f, 0.0)) for f in FACTOR_FIELDS]
    
    feat_29 = np.append(feat_selected, np.array(factor_vals, dtype=np.float64))
    return feat_29, np.array(feat, dtype=np.float64)  # (29维精选, 38维原始)


def score_stock(code, rows=None, conn=None, as_of_date=None):
    """
    个股评分入口
    参数:
        code: str, 如 '000001' (stock_code, 无后缀)
        rows: 可选，旧接口保留参数
        conn: 可选 DuckDB 连接，不传则自动开
        as_of_date: 可选，评估基准日期 'YYYYMMDD'（历史回算用，防止未来数据泄漏）
    返回:
        dict: {reg_pred, reg40_pred, fusion, fusion_avg, final_score, ...}
    """
    _load_models()
    if _reg20_model is None and _reg40_model is None and _reg10_model is None:
        return {'reg_pred': 0, 'reg40_pred': 0, 'fusion': 0, 'fusion_avg': 0,
                'final_score': 0, 'reg10_pred': 0, 'lstm': 50, 'cls27_prob': 0.5,
                'fusion_v9': 0}
    
    own_conn = conn is None
    if own_conn:
        conn = _safe_connect()
    try:
        feat_29, feat_38 = _compute_ml_features(code, conn, as_of_date=as_of_date)
        if feat_29 is None:
            return None
        # 取最新日期用于 GTJA
        latest_ts = conn.execute(
            f"SELECT MAX(trade_date) FROM daily WHERE ts_code LIKE '{code}%'"
        ).fetchone()[0]
        latest_date_str = f"{str(latest_ts)[:4]}-{str(latest_ts)[4:6]}-{str(latest_ts)[6:8]}"
    except Exception as e:
        print(f"  [scoring] {code} 特征计算失败: {e}")
        if own_conn:
            conn.close()
        return None
    
    # 10d预测（v3：从38维原始特征选31个量价特征）
    reg10_pred = 0.0
    if _reg10_model is not None and _stats10:
        try:
            f10 = np.array([feat_38[j] for j in PV_INDICES], dtype=np.float64).reshape(1, -1)
            for j in range(len(PV_INDICES)):
                key = f'feat_{j}'
                if key in _stats10:
                    s = _stats10[key]
                    if s['std'] > 0:
                        f10[0, j] = np.clip(f10[0, j], s['low'], s['high'])
                        f10[0, j] = (f10[0, j] - s['mean']) / s['std']
            f10 = np.nan_to_num(f10, nan=0.0)
            reg10_pred = float(_reg10_model.predict(f10)[0])
        except Exception as e:
            print(f"  [scoring] {code} 10d预测失败: {e}")

    # 20d预测（v2: 0926重训，31维 PV_INDICES 口径 = 与10d同一列序；旧29维mac_v1退役 models/retired_20260926/）
    reg20_pred = 0.0
    if _reg20_model is not None and _stats20:
        try:
            f20 = np.array([feat_38[j] for j in PV_INDICES], dtype=np.float64).reshape(1, -1)
            f20 = _standardize(f20, _stats20)
            f20 = np.nan_to_num(f20, nan=0.0)
            reg20_pred = float(_reg20_model.predict(f20)[0])
        except Exception as e:
            print(f"  [scoring] {code} 20d预测失败: {e}")

    # 40d预测
    reg40_pred = 0.0
    if _reg40_model is not None and _stats40:
        try:
            # v8 口径(0927重训, 2019起样本): BASE_KEEP 26维 + stk_factor(kdj_k,cci,rsi_12) = 29维
            # 与训练脚本 _cron_retrain_build_v8_2019_0927.py 同式（同 clip+standardize stats）
            keep26 = [float(feat_38[j]) for j in BASE_KEEP_INDICES]
            ts_code = f"{code}.SH" if code.startswith(('6','68')) else (f"{code}.BJ" if code.startswith('9') else f"{code}.SZ")
            fac = [0.0, 0.0, 0.0]
            try:
                row_fac = conn.execute(
                    "SELECT kdj_k, cci, rsi_12 FROM stk_factor WHERE ts_code = ? ORDER BY trade_date DESC LIMIT 1",
                    [ts_code]).fetchone()
                if row_fac:
                    fac = [float(v) if v is not None else 0.0 for v in row_fac]
            except Exception:
                pass
            f40 = np.array(keep26 + fac, dtype=np.float64).reshape(1, -1)
            f40 = _standardize(f40, _stats40)
            f40 = np.nan_to_num(f40, nan=0.0)
            reg40_pred = float(_reg40_model.predict(f40)[0])
        except Exception as e:
            print(f"  [scoring] {code} 40d预测失败: {e}")

    if own_conn:
        conn.close()
    
    # 融合(0927 用户拍板 v8): 0.25×reg10 + 0.75×reg40（reg20 剔除出融合分，字段照旧落库仅供观察）。
    # 依据: 344评估日 日均IC差 +0.0101 NW-t(lag5)=3.57; 三臂回测 生产-3.5%→v8融合+14.1%全段年化(B臂同卖法).
    # 旧公式: 20d×0.375+40d×0.625(0927上午); 更旧 10×0.20+20×0.30+40×0.50(0803)。
    fusion = reg10_pred * 0.25 + reg40_pred * 0.75

    return {
        'reg_pred': round(reg20_pred, 1),      # 20d预测百分数
        'reg40_pred': round(reg40_pred, 1),     # 40d预测百分数
        'reg10_pred': round(reg10_pred, 4),     # 10d预测百分数（保留4位，避免0.01阶梯离散化）
        'reg20_pred': round(reg20_pred, 1),
        'fusion': round(fusion, 1),             # 融合百分数
        'fusion_avg': round(fusion, 1),
        'fusion_v9': round(fusion, 1),
        'lstm': 50,
        'cls27_prob': 0.5,
        'final_score': round(fusion, 1),
    }


_etf_model = None
_etf_stats = {}


def _load_etf_model():
    global _etf_model, _etf_stats
    if _etf_model is not None:
        return
    if ETF_MODEL_PATH.exists():
        _etf_model = lgb.Booster(model_file=str(ETF_MODEL_PATH))
        print(f"  [scoring] ETF模型已加载 ({_etf_model.num_trees()}棵树)")
        if ETF_STATS_PATH.exists():
            with open(ETF_STATS_PATH) as f:
                _etf_stats = json.load(f)


def score_etf(ts_code, as_of_date=None):
    """ETF评分入口，返回 {score, prediction}
    as_of_date: 信号日 YYYYMMDD（历史补算用，评分只用截至该日的数据，防未来泄漏；
    None = 用全量最新数据）。2026-08-03 新增，参照股票模型 score_stock 的 as_of 透传。"""
    _load_etf_model()
    if _etf_model is None:
        return None
    
    conn = _safe_connect()
    try:
        if as_of_date:
            rows = conn.execute(f"""
                SELECT trade_date, close, vol, COALESCE(pct_chg,0)
                FROM fund_daily WHERE ts_code='{ts_code}' AND trade_date <= '{as_of_date}'
                ORDER BY trade_date
            """).fetchall()
        else:
            rows = conn.execute(f"""
                SELECT trade_date, close, vol, COALESCE(pct_chg,0)
                FROM fund_daily WHERE ts_code='{ts_code}'
                ORDER BY trade_date
            """).fetchall()
        if len(rows) < 140:
            return None
        
        closes = [float(r[1]) for r in rows]
        volumes = [float(r[2]) for r in rows]
        pcts = [float(r[3])/100.0 for r in rows]
        
        from scipy.stats import skew
        feat_24 = _compute_etf_features(closes, volumes, pcts)
        if feat_24 is None:
            return None
        
        f = np.array(feat_24, dtype=np.float64).reshape(1, -1)
        for j in range(24):
            key = f'feat_{j}'
            if key in _etf_stats:
                s = _etf_stats[key]
                if s['std'] > 0:
                    f[0, j] = np.clip(f[0, j], s['low'], s['high'])
                    f[0, j] = (f[0, j] - s['mean']) / s['std']
        f = np.nan_to_num(f, nan=0.0)
        pred = float(_etf_model.predict(f)[0])
        
        return {
            'prediction': round(pred, 2),
            'score': round(max(0, min(100, 50 + pred * 5)), 1),
            'ts_code': ts_code,
        }
    except Exception as e:
        print(f"  [scoring] ETF {ts_code} 评分失败: {e}")
        return None
    finally:
        conn.close()


def _compute_etf_features(closes, volumes, pcts):
    """ETF纯量价特征（24维，同训练脚本）"""
    import numpy as np
    from scipy.stats import skew as skew_fn
    
    FEAT_WIN = 120
    c = np.array(closes[-FEAT_WIN:], dtype=np.float64)
    v = np.array(volumes[-FEAT_WIN:], dtype=np.float64)
    p = np.array(pcts[-FEAT_WIN:], dtype=np.float64)
    lc = c[-1]
    n = len(c)
    if n < 60:
        return None
    
    chg5 = lc/c[-5]-1 if n>=5 else 0
    chg10 = lc/c[-10]-1 if n>=10 else 0
    chg20 = lc/c[-20]-1 if n>=20 else 0
    chg60 = lc/c[-60]-1 if n>=60 else 0
    
    ma5 = np.mean(c[-5:]) if n>=5 else lc
    ma10 = np.mean(c[-10:]) if n>=10 else lc
    ma20 = np.mean(c[-20:]) if n>=20 else lc
    ma60 = np.mean(c[-60:]) if n>=60 else lc
    d5 = lc/ma5-1; d10 = lc/ma10-1; d20 = lc/ma20-1; d60 = lc/ma60-1
    
    bull1 = 1.0 if (ma5>ma10>ma20) else 0.0
    bull2 = 1.0 if (ma20>ma60) else 0.0
    
    w20 = c[-20:] if n>=20 else c
    rl20, rh20 = np.min(w20), np.max(w20)
    rr = (rh20-rl20)/rl20*100 if rl20>0 else 0
    std20 = np.std(w20)/np.mean(w20)*100 if np.mean(w20)>0 else 0
    vols20 = v[-20:] if n>=20 else v
    vr = vols20[-1]/np.mean(vols20) if np.mean(vols20)>0 else 1.0
    pos = (lc-rl20)/(rh20-rl20)*100 if rh20!=rl20 else 50
    nh = 1.0 if lc>rh20*0.97 else 0.0
    vpc = 1.0 if chg5>0 and vr>1.2 else 0.0
    
    c1d = p[-1] if len(p)>0 else 0.0
    c3d = lc/c[-3]-1 if n>=3 else 0.0
    
    skew_val = float(skew_fn(w20)) if len(w20)>=20 else 0.0
    p20 = np.sign(p[-20:]) if n>=20 else np.sign(p) if len(p)>0 else np.array([0.0])
    dn = 0
    for s in reversed(np.sign(p20)):
        if s<0: dn += 1
        else: break
    up_ratio = np.sum(np.sign(p[-10:])>0)/10.0 if n>=10 else 0.5
    
    vol_chg = 0.0
    if n>=60:
        vo = float(np.std(p[-59:-20])*np.sqrt(252))
        vn = float(np.std(p[-20:])*np.sqrt(252))
        vol_chg = vn/vo-1 if vo>0 else 0.0
    
    sl5 = sl10 = 0.0
    if len(w20)>=10:
        x5=np.arange(5); y5=w20[-5:]
        x10=np.arange(10); y10=w20[-10:]
        d5n=np.sum((x5-x5.mean())**2)
        d10n=np.sum((x10-x10.mean())**2)
        sl5=float(np.sum((x5-x5.mean())*(y5-y5.mean()))/d5n) if d5n>0 else 0
        sl10=float(np.sum((x10-x10.mean())*(y10-y10.mean()))/d10n) if d10n>0 else 0
    accel = sl5 - sl10
    
    return [chg5,chg10,chg20,chg60,
            d5,d10,d20,d60,
            bull1,bull2,rr,std20,vr,pos,nh,vpc,
            c1d,c3d,
            skew_val,dn,up_ratio,
            vol_chg,sl5,accel]

