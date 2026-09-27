"""Tushare特征工程共享模块 v6 — 匹配retrain_20d_fixed.py训练管道
- 双库连接：tushare.db (主) + tushare.db (指数补充)
- 前复权处理
- 特征计算 (38基础 + 11GTJA = 49维，与retrain_20d_fixed.py完全一致)
- 指数代码映射

特征顺序（Column_0 ~ Column_48）：
  0-4:   chg5,chg10,chg20,chg60,chg120  (涨跌幅)
  5-9:   d5,d10,d20,d60,d120  (均线偏离)
  10-11: bull1,bull2  (形态)
  12-17: rr,std20,vr,pos,nh,vpc  (量价波动)
  18-19: c1d,c3d  (短期动量)
  20-22: ep,bp,ln_cap  (估值)
  23-25: ex5,ex10,ex20  (超额收益)
  26-27: skew20,kurt20  (分布特征)
  28-29: dn_streak,up_ratio10  (趋势强度)
  30-31: vol_chg,rel_str  (量能/相对强弱)
  32-35: kurt60,slope5,slope10,accel  (高阶趋势)
  36-37: vp_shrink,vp_div  (量价背离)
  38-48: GTJA_0 ~ GTJA_10 (GTJA因子)
"""
import numpy as np
import duckdb
from pathlib import Path
from scipy.stats import skew, kurtosis

# ── 路径 ──
TUSHARE_DB = Path.home() / '.hermes' / 'stockdb' / 'tushare.db'
GTJA_COMPACT_PKL = Path.home() / '.hermes' / 'stockdb' / 'models' / 'gtja_compact.pkl'

# ── 特征定义（38基础） ──
BASE_FEAT_NAMES = [
    'chg5','chg10','chg20','chg60','chg120',   # 0-4: 涨跌幅
    'd5','d10','d20','d60','d120',             # 5-9: 均线偏离
    'bull1','bull2',                             # 10-11: 形态
    'rr','std20','vr','pos','nh','vpc',         # 12-17: 量价波动
    'c1d','c3d',                                 # 18-19: 短期动量
    'ep','bp','ln_cap',                          # 20-22: 估值
    'ex5','ex10','ex20',                         # 23-25: 超额收益
    'skew20','kurt20',                           # 26-27: 分布特征
    'dn_streak','up_ratio10',                    # 28-29: 趋势强度
    'vol_chg','rel_str',                         # 30-31: 量能/相对强弱
    'kurt60','slope5','slope10','accel',         # 32-35: 高阶趋势
    'vp_shrink','vp_div',                        # 36-37: 量价背离
]
N_BASE = len(BASE_FEAT_NAMES)  # 38

# GTJA因子（取前11个，与训练一致：sorted(gtja_c.keys())[:11]）
GTJA_CODES = ['gtja_001','gtja_002','gtja_003','gtja_004','gtja_005',
              'gtja_006','gtja_007','gtja_008','gtja_009','gtja_010','gtja_011']

# 指数代码映射（匹配 index_daily 实际存在的指数）
BOARD_IDX = {
    '688':  '000688',     # 科创板
    '30':   '000300',     # 创业板
    '002':  '000016',     # 中小板
    '00':   '000001',     # 深市主板
    '6':    '000001',     # 沪市主板
}

FEAT_WIN = 120  # 需要120天历史计算特征


# ── 数据库连接 ──

def get_tushare_db():
    """打开tushare.db只读连接（走 core.db 保护层，防损坏）"""
    from core.db import get_tushare_db as _protected_db
    return _protected_db()


# ── 指数数据加载 ──

def load_index_data():
    """从tushare.db加载各板块指数数据（用于超额收益计算）
    返回: {idx_code: {'dates': [date_str], 'dict': {date_str: close}}}
    """
    con = get_tushare_db()
    result = {}
    # 加载所有需要的指数
    for idx_code in BOARD_IDX.values():
        rows = con.execute("""
            SELECT date, close FROM index_daily
            WHERE index_code=? ORDER BY date
        """, [idx_code]).fetchall()
        if rows:
            dates = [str(r[0])[:10] for r in rows]
            d = {str(r[0])[:10]: float(r[1]) for r in rows}
            result[idx_code] = {'dates': dates, 'dict': d}
    con.close()
    return result


def get_board_index(code):
    """根据股票代码返回对应板块指数（默认上证）"""
    code_short = code.split('.')[0] if '.' in code else code
    for prefix in ['688', '30', '002'] + ['92']:
        if code_short.startswith(prefix):
            return BOARD_IDX.get(prefix, '000001')
    if code_short.startswith('00'):
        return BOARD_IDX['00']
    if code_short.startswith('6'):
        return BOARD_IDX['6']
    return '000001'


# ── stk_factor 因子读取 ──

# 自算指标库接入 (2026-08-26, 本机调试/切换用):
# SELF_IND=1 时 get_factor_from_db 优先从 indicators.db 读自算指标(kdj_k/cci/rsi_12 等),
# 未命中回退原 stk_factor 逻辑。默认不开启, 行为与原来完全一致。
_SELF_CONN = None
_SELF_CACHE = {}  # (ts_code, dt) -> dict 当日自算指标行

def _get_self_factor(ts_code_full, dt_clean, factor_fields):
    """从 indicators.db 读自算指标, 返回 {f: v} 或 None"""
    global _SELF_CONN
    try:
        if _SELF_CONN is None:
            import duckdb as _dk
            _p = Path.home() / '.hermes' / 'stockdb' / 'indicators.db'
            if not _p.exists():
                return None
            _SELF_CONN = _dk.connect(str(_p), read_only=True)
        key = (ts_code_full, dt_clean)
        if key not in _SELF_CACHE:
            cur = _SELF_CONN.execute(
                "SELECT * FROM indicator_bfq WHERE ts_code=? AND trade_date=?",
                [ts_code_full, dt_clean])
            row = cur.fetchone()
            cols = [d[0] for d in cur.description]
            _SELF_CACHE[key] = dict(zip(cols, row)) if row else None
        d = _SELF_CACHE.get(key)
        if not d:
            return None
        out = {}
        for f in factor_fields:
            if f.startswith('rsi_') and f[4:].isdigit():
                v = d.get(f'rsi_bfq_{f[4:]}')
            else:
                v = d.get(f + '_bfq')
            out[f] = float(v) if v is not None else None
        if all(v is None for v in out.values()):
            return None
        return {f: (v if v is not None else 0.0) for f, v in out.items()}
    except Exception:
        return None


def get_factor_from_db(code, dt_clean, factor_fields, conn):
    """从 stk_factor 表读取指定日期和字段的因子值
    code: stock_code (如 '000690')
    dt_clean: 日期字符串 (如 '20260713')
    factor_fields: 字段名列表 (如 ['kdj_k', 'atr', 'rsi_12'])
    conn: duckdb连接

    2026-08-01 修复：stk_factor 直接列(如 kdj_k/cci/rsi_12)因列名不匹配
    (接口返回 kdj_k_bfq/cci_bfq/rsi_bfq_12 等) 一直是 0。
    真实因子在 extra JSON 里。改为优先从 extra 读 _bfq 键，
    与训练特征 core/features.py._load_stk_factor 的取值键一致；
    找不到再回退直接列。
    2026-08-26 自算接入: SELF_IND=1 时优先读 indicators.db(自算指标),
    未命中回退本逻辑。
    """
    import os
    if os.environ.get('SELF_IND') == '1':
        # 修复(0926): 北交所(9开头)在 tushare 表中后缀是 .BJ，旧写法映射到 .SH → 因子恒 0
        if code.startswith('9'):
            ts_code_full0 = f"{code}.BJ"
        elif code.startswith(('6', '68')):
            ts_code_full0 = f"{code}.SH"
        else:
            ts_code_full0 = f"{code}.SZ"
        _sv = _get_self_factor(ts_code_full0, dt_clean, factor_fields)
        if _sv is not None:
            return _sv
        # 2026-08-28 审计修复：自算未命中回退 stk_factor 时留痕——双轨口径已知有差异，
        # 静默混用会产生无法归因的评分漂移（2026-08-26 对拍口径）。
        print(f"  ⚠️ SELF_IND回退: {ts_code_full0} {dt_clean} 自算指标缺失, 本只用 stk_factor 口径")
    import json
    # 修复(0926): 北交所(9开头)在 tushare 表中后缀是 .BJ，旧写法映射到 .SH → 因子恒 0
    if code.startswith('9'):
        ts_code_full = f"{code}.BJ"
    elif code.startswith(('6', '68')):
        ts_code_full = f"{code}.SH"
    else:
        ts_code_full = f"{code}.SZ"
    
    def _resolve(extra_dict, f):
        """在 extra JSON 里解析因子 f 的 _bfq 值"""
        if not extra_dict:
            return None
        # 1) 精确: f + '_bfq' (如 kdj_k → kdj_k_bfq, cci → cci_bfq)
        key = f + '_bfq'
        if key in extra_dict and extra_dict[key] is not None:
            return float(extra_dict[key])
        # 2) rsi 特殊命名: rsi_12 → rsi_bfq_12
        if f.startswith('rsi_') and f[4:].isdigit():
            key2 = f'rsi_bfq_{f[4:]}'
            if key2 in extra_dict and extra_dict[key2] is not None:
                return float(extra_dict[key2])
        # 3) 模糊: 键含 f 且含 _bfq (如 f='kdj_k' 命中 kdj_k_bfq)
        for k, v in extra_dict.items():
            if f in k and '_bfq' in k and v is not None:
                return float(v)
        return None
    
    # 1. 查当天 extra
    row = conn.execute("""
        SELECT extra FROM stk_factor
        WHERE ts_code=? AND trade_date=?
        ORDER BY trade_date DESC LIMIT 1
    """, [ts_code_full, dt_clean]).fetchone()
    
    if row and row[0]:
        try:
            ed = json.loads(row[0])
            vals = {f: _resolve(ed, f) for f in factor_fields}
            if any(v is not None for v in vals.values()):
                return {f: (vals[f] if vals[f] is not None else 0.0) for f in factor_fields}
        except Exception:
            pass
    
    # 2. 回退：查最近的 extra
    row = conn.execute("""
        SELECT extra FROM stk_factor
        WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1
    """, [ts_code_full]).fetchone()
    if row and row[0]:
        try:
            ed = json.loads(row[0])
            vals = {f: _resolve(ed, f) for f in factor_fields}
            if any(v is not None for v in vals.values()):
                return {f: (vals[f] if vals[f] is not None else 0.0) for f in factor_fields}
        except Exception:
            pass
    
    # 3. 最后回退：直接列（历史兼容）
    fields_str = ', '.join(factor_fields)
    rows = conn.execute(f"""
        SELECT {fields_str} FROM stk_factor
        WHERE ts_code=? AND trade_date=?
        ORDER BY trade_date DESC LIMIT 1
    """, [ts_code_full, dt_clean]).fetchone()
    if not rows:
        rows = conn.execute(f"""
            SELECT {fields_str} FROM stk_factor
            WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1
        """, [ts_code_full]).fetchone()
    if rows:
        return {factor_fields[i]: float(rows[i]) if rows[i] is not None else 0.0 for i in range(len(factor_fields))}
    return {f: 0.0 for f in factor_fields}


# ── 前复权 ──

def apply_forward_adjust(closes, highs, lows, adj_factors):
    """应用前复权：adj_close[i] = raw_close[i] * adj_factor[i] / latest_adj"""
    if len(adj_factors) == 0:
        return closes, highs, lows
    
    latest_factor = max(f for _, f in adj_factors)
    if latest_factor <= 0:
        return closes, highs, lows
    
    adj_map = {str(d)[:10]: f for d, f in adj_factors}
    
    # Forward-fill factors (ascending date order of rows)
    norm_factors = []
    current_f = 1.0
    for i, dt in enumerate(adj_map if len(adj_factors) > 0 else [f'{i}' for i in range(len(closes))]):
        if isinstance(dt, str):
            pass
        # Use simple index-based matching since adj_factors may have different format
        norm_factors.append(current_f)
    
    closes = np.array(closes, dtype=np.float64) * 1.0  # identity if no factors
    highs = np.array(highs, dtype=np.float64) * 1.0
    lows = np.array(lows, dtype=np.float64) * 1.0
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


# ── 特征计算（核心：与retrain_20d_fixed.py完全一致） ──

def compute_features(closes, highs, lows, volumes, pcts, idx_close_dict, val_dict, dates=None):
    """计算38个基础特征，顺序与retrain_20d_fixed.py完全一致
    
    closes/highs/lows/volumes/pcts: numpy数组（窗口内全部历史）
    idx_close_dict: {date_str: close} 指数收盘数据（上证指数）
    val_dict: {'ep': float, 'bp': float, 'ln_cap': float}
    dates: 窗口内日期序列(与closes等长, 0927新ex口径必需; 缺省时ex退化为chg)
    
    Returns: np.array of shape (38,)
    """
    c = np.array(closes[-FEAT_WIN:], dtype=np.float64)
    h = np.array(highs[-FEAT_WIN:], dtype=np.float64)
    l = np.array(lows[-FEAT_WIN:], dtype=np.float64)
    v = np.array(volumes[-FEAT_WIN:], dtype=np.float64)
    p = np.array(pcts[-FEAT_WIN:], dtype=np.float64)
    lc = c[-1]

    n = len(c)  # should be FEAT_WIN (120) but handle shorter
    
    # ── 0-4: chg5,chg10,chg20,chg60,chg120 (涨跌幅) ──
    chg5 = lc / c[-5] - 1 if n >= 5 else 0.0
    chg10 = lc / c[-10] - 1 if n >= 10 else 0.0
    chg20 = lc / c[-20] - 1 if n >= 20 else 0.0
    chg60 = lc / c[-60] - 1 if n >= 60 else 0.0
    chg120 = lc / c[0] - 1 if n > 0 else 0.0
    
    # ── 5-9: d5,d10,d20,d60,d120 (均线偏离) ──
    ma5 = np.mean(c[-5:]) if n >= 5 else lc
    ma10 = np.mean(c[-10:]) if n >= 10 else lc
    ma20 = np.mean(c[-20:]) if n >= 20 else lc
    ma60 = np.mean(c[-60:]) if n >= 60 else lc
    ma_all = np.mean(c) if n > 0 else lc
    d5 = lc / ma5 - 1
    d10 = lc / ma10 - 1
    d20 = lc / ma20 - 1
    d60 = lc / ma60 - 1
    d120 = lc / ma_all - 1
    
    # ── 10-11: bull1,bull2 (形态) ──
    bull1 = 1.0 if (ma5 > ma10 and ma10 > ma20) else 0.0
    bull2 = 1.0 if (ma20 > ma60) else 0.0
    
    # ── 12-17: rr,std20,vr,pos,nh,vpc (量价波动) ──
    w20 = c[-20:] if n >= 20 else c[:]
    rl20, rh20 = np.min(w20), np.max(w20)
    rr = (rh20 - rl20) / rl20 * 100 if rl20 > 0 else 0.0
    std20 = np.std(w20) / np.mean(w20) * 100 if np.mean(w20) > 0 else 0.0
    
    vols20 = v[-20:] if n >= 20 else v[:]
    vr = vols20[-1] / np.mean(vols20) if np.mean(vols20) > 0 else 1.0
    pos = (lc - rl20) / (rh20 - rl20) * 100 if rh20 != rl20 else 50.0
    nh = 1.0 if lc > rh20 * 0.97 else 0.0
    vpc = 1.0 if chg5 > 0 and vr > 1.2 else 0.0
    
    # ── 18-19: c1d,c3d (短期动量) ──
    c1d = p[-1] if len(p) > 0 else 0.0
    c3d = lc / c[-3] - 1 if n >= 3 and c[-3] > 0 else 0.0
    
    # ── 20-22: ep,bp,ln_cap (估值) ──
    ep = val_dict.get('ep', 0.5)
    bp = val_dict.get('bp', 0.5)
    ln_cap = val_dict.get('ln_cap', 22.0)
    
    # ── 23-25: ex5,ex10,ex20 (超额收益, 新口径 0927 用户拍板) ──
    # 基准日=个股窗口日历位置 -5/-10/-20（与 chg5/10/20 同窗口同基准），
    # 不再用指数日历倒数第5/10/20（旧口径与个股回看日错位，ex 语义失真）。
    # 指数价按基准日精确查找（idx dict 键=日期），查不到该日则该项=chg（超额视为0）。
    if idx_close_dict and n >= 20 and dates is not None:
        all_dates = [str(d) for d in dates]
        _dashes = '-' in next(iter(idx_close_dict))
        def _idx_at(pos):
            d = all_dates[pos]
            key = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if _dashes and '-' not in d else d
            return idx_close_dict.get(key)
        idx_now = _idx_at(n - 1)
        if idx_now:
            _b5, _b10, _b20 = _idx_at(n - 5), _idx_at(n - 10), _idx_at(n - 20)
            ex5 = chg5 - ((idx_now / _b5 - 1) if _b5 else 0.0)
            ex10 = chg10 - ((idx_now / _b10 - 1) if _b10 else 0.0)
            ex20 = chg20 - ((idx_now / _b20 - 1) if _b20 else 0.0)
        else:
            ex5 = ex10 = ex20 = 0.0
    else:
        ex5 = ex10 = ex20 = 0.0
    
    # ── 26-27: skew20,kurt20 (分布特征) ──
    skew20_val = float(skew(w20)) if len(w20) >= 20 else 0.0
    kurt20_val = float(kurtosis(w20, fisher=False)) if len(w20) >= 20 else 3.0
    
    # ── 28-29: dn_streak,up_ratio10 (趋势强度) ──
    p20 = np.sign(p[-20:]) if n >= 20 else np.sign(p) if len(p) > 0 else np.array([0.0])
    
    # Down streak: count consecutive negative returns from end
    dn_streak_val = 0
    for s in reversed(np.sign(p20)):
        if s < 0:
            dn_streak_val += 1
        else:
            break
    
    up_ratio10 = np.sum(np.sign(p[-10:]) > 0) / 10.0 if n >= 10 else 0.5
    
    # ── 30-31: vol_chg,rel_str (量能变化/相对强弱) ──
    if n >= 60:
        vo = float(np.std(p[-59:-20]) * np.sqrt(252))  # volume change over 40-60 days ago
        vn = float(np.std(p[-20:]) * np.sqrt(252))      # volume change over last 20 days
        vol_chg_val = vn / vo - 1 if vo > 0 else 0.0
    else:
        vol_chg_val = 0.0
    
    ma20_now = np.mean(w20)
    w60 = c[-60:] if n >= 60 else c[:]
    ma60_now = np.mean(w60) if len(w60) > 0 else ma20_now
    rel_str_val = chg5 - (ma20_now / ma60_now - 1) if ma60_now > 0 else 0.0
    
    # ── 32-35: kurt60,slope5,slope10,accel (高阶趋势) ──
    w60 = c[-60:] if n >= 60 else c[:]
    kurt60_val = float(kurtosis(w60, fisher=False)) if len(w60) >= 60 else 3.0
    
    if len(w20) >= 10:
        x5 = np.arange(5)
        y5 = w20[-5:]
        denom5 = np.sum((x5 - x5.mean())**2)
        slope5_val = float(np.sum((x5 - x5.mean()) * (y5 - y5.mean())) / denom5) if denom5 > 0 else 0.0
        
        x10 = np.arange(10)
        y10 = w20[-10:]
        denom10 = np.sum((x10 - x10.mean())**2)
        slope10_val = float(np.sum((x10 - x10.mean()) * (y10 - y10.mean())) / denom10) if denom10 > 0 else 0.0
        
        accel_val = slope5_val - slope10_val
    else:
        slope5_val = slope10_val = accel_val = 0.0
    
    # ── 36-37: vp_shrink,vp_div (量价背离) ──
    vr20 = vols20[-1] / np.mean(vols20) if np.mean(vols20) > 0 else 1.0
    vp_shrink_val = 1.0 if chg5 < -0.01 and vr20 < 0.7 else 0.0
    vp_div_val = 1.0 if ((chg5 > 0 and vr20 < 0.8) or (chg5 < 0 and vr20 > 1.2)) else 0.0
    
    return np.array([
        # 0-4: chg
        chg5, chg10, chg20, chg60, chg120,
        # 5-9: deviation
        d5, d10, d20, d60, d120,
        # 10-11: bull
        bull1, bull2,
        # 12-17: rr,std,vr,pos,nh,vpc
        rr, std20, vr, pos, nh, vpc,
        # 18-19: short-term momentum
        c1d, c3d,
        # 20-22: valuation
        ep, bp, ln_cap,
        # 23-25: excess returns
        ex5, ex10, ex20,
        # 26-27: distribution
        skew20_val, kurt20_val,
        # 28-29: trend strength
        dn_streak_val, up_ratio10,
        # 30-31: volume/relative strength
        vol_chg_val, rel_str_val,
        # 32-35: higher-order trends
        kurt60_val, slope5_val, slope10_val, accel_val,
        # 36-37: vol-price divergence
        vp_shrink_val, vp_div_val,
    ], dtype=np.float64)


# ── GTJA因子加载（使用gtja_compact.pkl，与训练一致） ──

def load_gtja_compact():
    """加载GTJA紧凑格式数据，返回 {factor_name: {code: {date_str: value}}}"""
    if not GTJA_COMPACT_PKL.exists():
        print("  [WARN] GTJA compact pkl not found, using zeros")
        return {}
    
    import pickle
    with open(GTJA_COMPACT_PKL, 'rb') as f:
        gtja_compact = pickle.load(f)
    
    # Return first 11 factors (with training)
    all_factors = sorted(gtja_compact.keys())[:11]
    result = {}
    for fn in all_factors:
        if fn in gtja_compact:
            result[fn] = gtja_compact[fn]
    
    return {k: result[k] for k in GTJA_CODES[:len(result)]}


def get_gtja_value(code, date_str, gtja_lookup):
    """从GTJA compact lookup中获取值，支持向前填充"""
    if not gtja_lookup:
        return 0.0
    
    values = []
    for factor_name in GTJA_CODES[:11]:
        code_dict = gtja_lookup.get(factor_name, {})
        stock_data = code_dict.get(code, {})
        
        val = 0.0
        # Direct lookup or forward-fill from recent dates
        if date_str in stock_data:
            val = stock_data[date_str]
        else:
            # Forward fill up to 15 days back (same as retrain_40d.py)
            all_dates = sorted(stock_data.keys())
            for i, d in enumerate(all_dates):
                if d >= date_str:
                    prev_idx = i - 1
                    for offset in range(15):
                        if prev_idx - offset >= 0:
                            val = stock_data[all_dates[prev_idx - offset]]
                    break
            else:
                # If date_str is after all dates, use the last available
                if all_dates and len(all_dates) > 0:
                    val = stock_data.get(all_dates[-1], 0.0)
        
        values.append(float(val) if val else 0.0)
    
    return values


# ── 标准化（与训练一致） ──

def compute_norm_stats(X_train):
    """从训练集计算标准化统计量"""
    stats = {}
    n_feats = X_train.shape[1]
    for j in range(n_feats):
        vals = X_train[:, j]
        valid = vals[~np.isnan(vals) & ~np.isinf(vals)]
        if len(valid) < 100:
            continue
        mean_v = float(np.mean(valid))
        std_v = float(np.std(valid, ddof=1))
        lo = float(np.percentile(valid, 0.5))
        hi = float(np.percentile(valid, 99.5))
        if std_v < 1e-10:
            std_v = 1.0
            lo = mean_v - 1
            hi = mean_v + 1
        stats[f'feat_{j}'] = {'mean': mean_v, 'std': std_v, 'low': lo, 'high': hi}
    return stats


def standardize_v6(X, stats):
    """标准化特征（与retrain_20d_fixed.py的norm函数一致）"""
    Xn = X.copy() if not isinstance(X, np.ndarray) else X.copy()
    n_feats = len(stats)
    for j in range(n_feats):
        key = f'feat_{j}'
        if key in stats:
            s = stats[key]
            if s['std'] > 0:
                Xn[:, j] = np.clip(Xn[:, j], s['low'], s['high'])
                Xn[:, j] = (Xn[:, j] - s['mean']) / s['std']
    return Xn
