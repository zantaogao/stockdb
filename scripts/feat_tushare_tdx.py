"""特征工程共享模块（tushare + TDX 双数据源）
|- 双库连接：tushare.db + tdx_stock_data.db
|- 前复权处理（或直接用TDX复权数据）
|- 特征计算 (30基础 + 2GTJA + 3市场 = 35维)
|- 指数、行业、市场趋势特征
"""
import numpy as np
import duckdb
import gzip
import pickle
from pathlib import Path
from collections import defaultdict
from bisect import bisect_left

# ── 路径 ──
TUSHARE_DB = Path.home() / '.hermes' / 'stockdb' / 'tushare.db'
TDX_DB = Path.home() / 'Desktop' / 'tdx_stock_data.db'
STOCK_DB = Path.home() / '.hermes' / 'stockdb' / 'stock.db'
GTJA_PKL = Path.home() / '.hermes' / 'stockdb' / 'gtja_signals.pkl.gz'

# ── 特征定义 ──
FEAT_WIN = 120  # 需要120天历史计算特征
BASE_FEAT_NAMES = [
    'chg5', 'chg10', 'chg20', 'chg60', 'chg120',
    'd5', 'd10', 'd20', 'd60', 'd120',
    'bull1', 'bull2', 'rr', 'std20', 'vr', 'pos',
    'nh', 'vpc', 'c1d', 'c3d', 'ep', 'bp', 'ln_cap',
    'ex5', 'ex10', 'ex20',
    'rsi14', 'adx14', 'vpd', 'trend_accel',
]
N_BASE = len(BASE_FEAT_NAMES)  # 30

# 市场级特征（每个日期相同）
MKT_FEAT_NAMES = ['vol_regime', 'idx_adx', 'ind_rotation']
N_MKT = len(MKT_FEAT_NAMES)  # 3

# GTJA因子（可配置）
GTJA_CODES = ['gtja_006', 'gtja_083']  # 2个

# 指数代码映射（tushare ts_code -> stock.db index_code）
IDX_MAP = {
    '000001.SH': '000001',   # 上证综指
    '399001.SZ': '399001',   # 深证综指
    '000300.SH': '000300',   # 沪深300
    '000905.SH': '000905',   # 中证500
    '000688.SH': '000688',   # 科创50
    '399006.SZ': '399006',   # 创业板指
    '000016.SH': '000016',   # 上证50
}

# 板块默认指数
BOARD_IDX = {
    '688':  '000688.SH',     # 科创板
    '30':   '399006.SZ',     # 创业板
    '002':  '000905.SH',     # 中小板
    '00':   '399001.SZ',     # 深市主板
    '6':    '000001.SH',     # 沪市主板
    '8':    '399852',        # 老三板（stock.db直用）
    '4':    '399852',        # 新三板
    '920':  '399852',        # 新三板
}

# ── 数据库连接 ──

def get_tushare_db():
    """打开tushare.db只读连接"""
    con = duckdb.connect(str(TUSHARE_DB), read_only=True)
    con.execute("SET threads=4")
    return con

def get_stock_db():
    """打开stock.db只读连接（用于指数）"""
    con = duckdb.connect(str(STOCK_DB), read_only=True)
    con.execute("SET threads=4")
    return con

# ── 指数数据加载 ──

def load_index_data():
    """从stock.db加载所有指数数据
    返回 {index_code: (sorted_dates, closes_dict)}
    sorted_dates: list of date_str for bisect
    closes_dict: {date_str: close} for lookup
    """
    con = get_stock_db()
    idx = {}
    rows = con.execute("""
        SELECT index_code, CAST(date AS VARCHAR) as ds, close
        FROM index_daily ORDER BY index_code, date
    """).fetchall()
    con.close()

    for code, ds, close in rows:
        ds_clean = ds.replace('-', '')[:10]
        if code not in idx:
            idx[code] = {'dates': [], 'dict': {}}
        idx[code]['dates'].append(ds_clean)
        idx[code]['dict'][ds_clean] = float(close)
    return idx

def get_board_index(ts_code):
    """根据股票代码返回对应板块指数"""
    code = ts_code.split('.')[0]  # 去掉 .SZ/.SH
    for prefix in ['688', '30', '002', '8', '4', '920']:
        if code.startswith(prefix):
            return BOARD_IDX.get(prefix)
    if code.startswith('00'):
        return BOARD_IDX['00']
    if code.startswith('6'):
        return BOARD_IDX['6']
    return '000001.SH'  # 默认上证综指

# ── TDX 数据源 ──

def get_tdx_db():
    """打开TDX数据库只读连接"""
    con = duckdb.connect(str(TDX_DB), read_only=True)
    con.execute("SET threads=4")
    return con

def load_index_data_tdx():
    """从TDX加载指数数据（含沪深300/上证综指等）
    返回 {index_code: {dates: [...], dict: {date: close}}}
    """
    con = get_tdx_db()
    idx = {}
    # TDX 中的指数：SH市场=上证系，SZ市场=深证系
    idx_codes = {
        '000001.SH': ('000001', 'sh'),
        '000300.SH': ('000300', 'sh'),
        '000016.SH': ('000016', 'sh'),
        '000688.SH': ('000688', 'sh'),
        '000905.SH': ('000905', 'sh'),
        '399001.SZ': ('399001', 'sz'),
        '399006.SZ': ('399006', 'sz'),
    }
    for icode, (code, mkt) in idx_codes.items():
        rows = con.execute(f"""
            SELECT date, close FROM daily
            WHERE code='{code}' AND market='{mkt}'
            ORDER BY date
        """).fetchall()
        if not rows:
            continue
        dates = [r[0].replace('-', '')[:10] for r in rows]
        d = {dates[i]: float(rows[i][1]) for i in range(len(rows))}
        idx[icode] = {'dates': dates, 'dict': d}
    con.close()
    return idx

def load_industry_map():
    """从tushare.db加载行业分类
    返回 {ts_code: industry_name}
    """
    con = duckdb.connect(str(TUSHARE_DB), read_only=True)
    rows = con.execute("""
        SELECT ts_code, COALESCE(industry, '其他') FROM stock_basic
    """).fetchall()
    con.close()
    return {r[0]: r[1] for r in rows if r[0]}

def ts_code_to_tdx(ts_code):
    """tushare ts_code -> TDX (code, market) 元组"""
    parts = ts_code.split('.')
    return parts[0], parts[1].lower()

# ── 市场级特征计算 ──

def compute_market_features_tdx(all_dates):
    """预计算每日市场特征
    all_dates: 所有出现的日期列表（用于插齐空缺）
    返回 {date_str: [vol_regime_norm, idx_adx, ind_rotation]}
    
    vol_regime_norm: 沪深300 20d波动率 -> Z-score
    idx_adx: 沪深300 ADX14
    ind_rotation: 行业轮动信号（TOP3-BOTTOM3行业5d收益差）
    """
    idx_data = load_index_data_tdx()
    industry_map = load_industry_map()
    
    # 获取沪深300数据
    hs300 = idx_data.get('000300.SH')
    if not hs300:
        print("  [WARN] 000300.SH not available, using default mkt features")
        return {d: [0.0, 25.0, 0.0] for d in all_dates}
    
    dates = hs300['dates']
    closes_300 = np.array([hs300['dict'][d] for d in dates], dtype=np.float64)
    
    # 1. 波动率区间（沪深300 20日滚动波动率）
    pcts_300 = np.diff(closes_300) / closes_300[:-1]
    vol_20d = []
    for i in range(len(pcts_300)):
        if i < 20:
            vol_20d.append(0.0)
        else:
            vol_20d.append(float(np.std(pcts_300[i-19:i+1]) * 100))
    vol_20d = np.array(vol_20d)
    vol_mean = np.mean(vol_20d)
    vol_std = np.std(vol_20d)
    if vol_std < 1e-10:
        vol_std = 1.0
    vol_norm = (vol_20d - vol_mean) / vol_std  # Z-score
    # 对齐：vol_norm 比 dates 少1（因为pct比close少1）
    vol_norm_aligned = np.concatenate([[0.0], vol_norm])
    
    # 2. 指数ADX（沪深300 ADX14）
    idx_adx_vals = []
    con = get_tdx_db()
    rows = con.execute("""
        SELECT date, close, high, low FROM daily
        WHERE code='000300' AND market='sh' ORDER BY date
    """).fetchall()
    con.close()
    hs_close = np.array([float(r[1]) for r in rows], dtype=np.float64)
    hs_high = np.array([float(r[2]) for r in rows], dtype=np.float64)
    hs_low = np.array([float(r[3]) for r in rows], dtype=np.float64)
    
    for i in range(len(hs_close)):
        if i < 28:  # need 2*period for ADX
            idx_adx_vals.append(25.0)
        else:
            idx_adx_vals.append(compute_adx(
                hs_high[max(0, i-119):i+1], hs_low[max(0, i-119):i+1],
                hs_close[max(0, i-119):i+1], period=14
            ))
    idx_adx_arr = np.array(idx_adx_vals)
    
    # 3. 行业轮动信号
    # 需要行业+每日收益率 => 从TDX和tushare加载
    # 先建立 code -> industry 映射（去掉.SH/.SZ后缀）
    code_to_ind = {}
    for ts, ind in industry_map.items():
        code = ts.split('.')[0]
        code_to_ind[code] = ind
    
    # 获取所有股票最近的涨跌幅数据（日频，从TDX）
    con = get_tdx_db()
    all_stock_rows = con.execute("""
        SELECT code, market, date, close FROM daily
        WHERE market IN ('sz', 'sh')
        ORDER BY code, market, date
    """).fetchall()
    con.close()
    
    # 按code+market分组
    stocks_data = defaultdict(list)
    for code, mkt, dt, close in all_stock_rows:
        if code.startswith(('0', '3', '6')) and len(code) == 6:  # A股
            stocks_data[(code, mkt)].append((str(dt)[:10], float(close)))
    
    # 每日各行业的平均5d收益
    date_inds_rets = defaultdict(lambda: defaultdict(list))
    for (code, mkt), sdata in stocks_data.items():
        ind = code_to_ind.get(code, '其他')
        if len(sdata) < 6:
            continue
        for i in range(5, len(sdata)):
            dt = sdata[i][0]
            ret_5d = sdata[i][1] / sdata[i-5][1] - 1
            date_inds_rets[dt][ind].append(ret_5d)
    
    date_set = set(dates)
    rotation_signal = {}
    for dt in sorted(date_set):
        if dt not in date_inds_rets:
            rotation_signal[dt] = 0.0
            continue
        ind_rets = date_inds_rets[dt]
        rets = [(ind, np.mean(vals)) for ind, vals in ind_rets.items() if len(vals) >= 3]
        if len(rets) < 6:
            rotation_signal[dt] = 0.0
            continue
        rets.sort(key=lambda x: -x[1])
        n_sig = max(1, len(rets) // 5)
        top = np.mean([r[1] for r in rets[:n_sig]])
        bot = np.mean([r[1] for r in rets[-n_sig:]])
        rotation_signal[dt] = (top - bot) * 100  # %
    
    # 组合
    date_to_idx = {d: i for i, d in enumerate(dates)}
    mkt_feat = {}
    for d in all_dates:
        # 向前查找最近日期
        dt = d
        while dt not in date_to_idx and dt > '20100101':
            dt_int = int(dt) - 1
            dt = str(dt_int)
            if len(dt) < 8:
                dt = dt.zfill(8)
        if dt in date_to_idx:
            i = date_to_idx[dt]
            v_reg = float(vol_norm_aligned[i])
            i_adx = float(idx_adx_arr[i])
            i_rot = rotation_signal.get(d, 0.0)
        else:
            v_reg = 0.0
            i_adx = 25.0
            i_rot = 0.0
        mkt_feat[d] = [v_reg, i_adx, i_rot]
    
    return mkt_feat

# ── 前复权 ──

def apply_forward_adjust(closes, highs, lows, adj_factors, dates):
    """应用前复权
    adj_factors: [(date_str, factor), ...] 按日期升序
    公式: adj_close[i] = raw_close[i] * adj_factor[i] / adj_factor[latest]
    """
    if len(adj_factors) == 0:
        return closes, highs, lows

    # adj_factor 归一化：除以最新因子
    latest_factor = adj_factors[-1][1]
    if latest_factor <= 0:
        return closes, highs, lows

    # 建因子查找字典
    adj_map = {str(d)[:10]: f for d, f in adj_factors}

    # 向前填充：每个日期用最近日期的因子
    norm_factors = []
    current_f = 1.0
    for i, dt in enumerate(dates):
        if dt in adj_map:
            current_f = adj_map[dt] / latest_factor
        norm_factors.append(current_f)

    closes = np.array(closes, dtype=np.float64) * np.array(norm_factors, dtype=np.float64)
    highs = np.array(highs, dtype=np.float64) * np.array(norm_factors, dtype=np.float64)
    lows = np.array(lows, dtype=np.float64) * np.array(norm_factors, dtype=np.float64)
    return closes, highs, lows

# ── 技术指标 ──

def compute_rsi(close, period=14):
    changes = np.diff(close)
    gains = np.where(changes > 0, changes, 0.0)
    losses = np.where(changes < 0, -changes, 0.0)
    if len(gains) < period:
        return 50.0
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

def compute_adx(high, low, close, period=14):
    n = len(high)
    if n < period * 2:
        return 25.0
    h, l, c = np.asarray(high[-period*8:], dtype=np.float64), np.asarray(low[-period*8:], dtype=np.float64), np.asarray(close[-period*8:], dtype=np.float64)
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    up = h[1:] - h[:-1]
    down = l[:-1] - l[1:]
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    atr = np.mean(tr[:period])
    if atr == 0:
        return 25.0
    plus_di = np.mean(plus_dm[:period]) / atr * 100.0
    minus_di = np.mean(minus_dm[:period]) / atr * 100.0
    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 25.0
    return abs(plus_di - minus_di) / di_sum * 100.0

def compute_vpd(pct_vals, vol_vals, period=20):
    c5 = np.mean(pct_vals[-5:])
    v5 = np.mean(vol_vals[-5:])
    v20 = np.mean(vol_vals) if len(vol_vals) >= period else np.mean(vol_vals)
    if v20 == 0:
        return 0.0
    vol_ratio = v5 / v20
    if c5 >= 0:
        return vol_ratio - 1.0
    else:
        return 1.0 - vol_ratio

# ── 特征计算 ──

def compute_features(closes, highs, lows, volumes, pcts, idx_closes, val_dict):
    """计算30个基础特征
    closes/highs/lows/volumes: numpy数组 (窗口内全部历史)
    pcts: 每日涨跌幅数组
    idx_closes: 指数收盘数组 (可为None)
    val_dict: {'ep': float, 'bp': float, 'ln_cap': float}
    """
    c = np.array(closes[-FEAT_WIN:], dtype=np.float64)
    h = np.array(highs[-FEAT_WIN:], dtype=np.float64)
    l = np.array(lows[-FEAT_WIN:], dtype=np.float64)
    v = np.array(volumes[-FEAT_WIN:], dtype=np.float64)
    p = np.array(pcts[-FEAT_WIN:], dtype=np.float64)
    lc = c[-1]

    # 涨跌幅
    chg5 = lc / c[-5] - 1
    chg10 = lc / c[-10] - 1
    chg20 = lc / c[-20] - 1
    chg60 = lc / c[-60] - 1
    chg120 = lc / c[0] - 1

    # 均线偏离
    ma5 = np.mean(c[-5:])
    ma10 = np.mean(c[-10:])
    ma20 = np.mean(c[-20:])
    ma60 = np.mean(c[-60:])
    d5 = lc / ma5 - 1
    d10 = lc / ma10 - 1
    d20 = lc / ma20 - 1
    d60 = lc / ma60 - 1
    d120 = lc / np.mean(c) - 1

    # 形态
    b1 = 1.0 if ma5 > ma10 > ma20 else 0.0
    b2 = 1.0 if ma20 > ma60 else 0.0
    rn = np.max(c[-20:]) - np.min(c[-20:])
    rr = rn / np.min(c[-20:]) * 100 if np.min(c[-20:]) > 0 else 0
    std20 = np.std(c[-20:]) / np.mean(c[-20:]) * 100

    # 量价
    vols = np.array(v[-20:], dtype=np.float64)
    vr = vols[-1] / np.mean(vols) if np.mean(vols) > 0 else 1.0
    rl, rh = np.min(c[-20:]), np.max(c[-20:])
    pos = (lc - rl) / (rh - rl) * 100 if rh != rl else 50.0
    nh = 1.0 if lc > rh * 0.97 else 0.0
    vpc = 1.0 if chg5 > 0 and vr > 1.2 else 0.0

    # 短期动量
    c1d = p[-1] if len(p) > 0 else 0.0
    c3d = lc / c[-3] - 1 if len(c) >= 3 and c[-3] > 0 else 0.0

    # 估值
    ep = val_dict.get('ep', 0.5)
    bp = val_dict.get('bp', 0.5)
    ln_cap = val_dict.get('ln_cap', 22.0)

    # 超额收益
    if idx_closes is not None and len(idx_closes) >= 20:
        idx = np.array(idx_closes, dtype=np.float64)
        ex5 = chg5 - (idx[-1] / idx[-5] - 1)
        ex10 = chg10 - (idx[-1] / idx[-10] - 1)
        ex20 = chg20 - (idx[-1] / idx[-20] - 1)
    else:
        ex5 = ex10 = ex20 = 0.0

    # 技术指标
    rsi14 = compute_rsi(c)
    adx14 = compute_adx(h, l, c)
    vpd_val = compute_vpd(p, vols)
    trend_accel = chg20 - chg60

    return np.array([
        chg5, chg10, chg20, chg60, chg120,
        d5, d10, d20, d60, d120,
        b1, b2, rr, std20, vr, pos,
        nh, vpc, c1d, c3d, ep, bp, ln_cap,
        ex5, ex10, ex20,
        rsi14, adx14, vpd_val, trend_accel,
    ], dtype=np.float32)

# ── GTJA ──

def load_gtja(gtja_codes=None):
    """加载GTJA因子，返回 lookup dict: {code: (dates, df)}"""
    if gtja_codes is None:
        gtja_codes = GTJA_CODES
    if not GTJA_PKL.exists():
        print("  [WARN] GTJA pickle not found, using zeros")
        return {}
    with gzip.open(str(GTJA_PKL), 'rb') as f:
        gtja_dict = pickle.load(f)
    lookups = {}
    for gn in gtja_codes:
        if gn not in gtja_dict:
            continue
        df = gtja_dict[gn]
        dates = sorted(df.index)
        dates_str = [str(d)[:10] for d in dates]
        lookups[gn] = (dates_str, df)
    return lookups

def get_gtja_value(code, date_str, lookup):
    """从GTJA lookup中获取值"""
    if lookup is None:
        return 0.0
    dates, df = lookup
    if code not in df.columns:
        return 0.0
    import bisect
    idx = bisect.bisect_right(dates, date_str) - 1
    # 向前查找最近有效值
    for offset in range(6):
        if idx - offset < 0:
            break
        pi = idx - offset
        d = dates[pi]
        try:
            val = df.loc[d, code]
            if val is not None and not np.isnan(val) and val != 0.0:
                return float(val)
        except:
            continue
    return 0.0

# ── 标准化 ──

def compute_norm_stats(X_train):
    """从训练集计算标准化统计量"""
    stats = {}
    n_feats = X_train.shape[1]
    for j in range(n_feats):
        vals = X_train[:, j]
        mean_v = float(np.mean(vals))
        std_v = float(np.std(vals))
        lo = float(np.percentile(vals, 1))
        hi = float(np.percentile(vals, 99))
        if std_v < 1e-10:
            std_v = 1.0
            lo = mean_v - 1
            hi = mean_v + 1
        stats[f'feat_{j}'] = {'mean': mean_v, 'std': std_v, 'low': lo, 'high': hi}
    return stats

def standardize(X, stats):
    """标准化特征"""
    Xn = X.copy()
    n_feats = X.shape[1]
    for j in range(n_feats):
        key = f'feat_{j}'
        if key in stats:
            s = stats[key]
            if s['std'] > 0:
                Xn[:, j] = np.clip(Xn[:, j], s['low'], s['high'])
                Xn[:, j] = (Xn[:, j] - s['mean']) / s['std']
    return Xn
