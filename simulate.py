#!/usr/bin/env python3
"""
模拟交易系统 v1
Web 面板 + 模拟账户管理 + 信号集成

用法: python3 simulate.py [--port 8080]
"""
import os, sys, json, subprocess, re, argparse, threading
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, date
from pathlib import Path
from io import StringIO
import urllib.request

BASE = Path.home() / '.hermes' / 'stockdb'
STOCK_DB = BASE / 'tushare.db'
HOLD_PATH = BASE / 'holdings.json'
ACCT_PATH = BASE / 'account.json'
SCRIPTS = BASE / 'scripts'
TRACK_PATH = BASE / 'stock_tracking.json'
MODEL_DIR = BASE / 'models'

# ── v4/v9/v10 模型加载（lazy） ──
_V4_REG = None
_V4_LSTM = None
_V4_GTJA = None
_V9_REG40 = None
_V9_STATS40 = {}
_V10_REG = None
_V10_STATS = {}
_USE_V9 = True  # 启用40d+10d模型融合

_lock = threading.Lock()

def _ensure_v4():
    global _V4_REG, _V4_LSTM, _V4_GTJA, _V9_REG40, _V9_STATS40, _V10_REG, _V10_STATS
    if _V4_REG is not None:
        return
    with _lock:
        if _V4_REG is not None:
            return
        import lightgbm as lgb, gzip, pickle
    reg_path = MODEL_DIR / 'lgb_reg_model.txt'
    if reg_path.exists():
        _V4_REG = lgb.Booster(model_file=str(reg_path))
    # 加载40日模型
    reg40_path = MODEL_DIR / 'lgb_reg_40d.txt'
    stats40_path = MODEL_DIR / 'v6_norm_stats_40d.json'
    if reg40_path.exists():
        _V9_REG40 = lgb.Booster(model_file=str(reg40_path))
    if stats40_path.exists():
        with open(stats40_path) as f:
            _V9_STATS40 = json.load(f)
    # 加载10日模型
    reg10_path = MODEL_DIR / 'lgb_reg_10d.txt'
    stats10_path = MODEL_DIR / 'v10_norm_stats.json'
    if reg10_path.exists():
        _V10_REG = lgb.Booster(model_file=str(reg10_path))
    if stats10_path.exists():
        with open(stats10_path) as f:
            _V10_STATS = json.load(f)
    lstm_path = BASE / 'lstm_pred.json'
    if lstm_path.exists():
        with open(lstm_path) as f:
            raw = json.load(f)
        vals = sorted(raw.values())
        _V4_LSTM = {k: (v - vals[0]) / (vals[-1] - vals[0] + 1e-10) * 100
                    for k, v in raw.items()}
    # GTJA因子预计算（lazy加载）
    pkl_path = Path.home() / '.hermes' / 'stockdb' / 'gtja_signals.pkl.gz'
    if pkl_path.exists():
        try:
            with gzip.open(str(pkl_path), 'rb') as f:
                _V4_GTJA = pickle.load(f)
            from core.features import _build_gtja_date_index
            _build_gtja_date_index(_V4_GTJA)
        except: pass

def _compute_v4_score(code, rows, conn):
    """返回 (reg_pct, lstm_score, fusion, fusion_v9, reg40_p, reg40_score, reg10_p) 或 None"""
    _ensure_v4()
    if _V4_REG is None or len(rows) < 120:
        return None
    try:
        from core.features import compute_raw_features, standardize_v5, get_gtja_signals
        import numpy as np
        
        base_raw, dt_str = compute_raw_features(code, rows, conn)
        if base_raw is None:
            return None
        
        # 20d模型：标准化（26维）+ GTJA（4维）+ 补齐到30维
        feat_v5 = standardize_v5(base_raw)
        if feat_v5 is None:
            feat_v5 = base_raw.copy()
        gtja_v = get_gtja_signals(code, dt_str, _V4_GTJA) if _V4_GTJA is not None else []
        feat_full = np.append(feat_v5, np.array(gtja_v, dtype=np.float64))
        while len(feat_full) < 30:
            feat_full = np.append(feat_full, np.float64(0))
        feat_full = np.nan_to_num(feat_full.reshape(1, -1), nan=0.0)
        reg_p = float(_V4_REG.predict(feat_full)[0])
        lstm_s = _V4_LSTM.get(code, 50) if _V4_LSTM else 50
        fusion = min(100, max(0, (reg_p*100+10)/50*100))
        
        # v9: 40日模型预测
        reg40_p = 0
        if _USE_V9 and _V9_REG40 is not None and _V9_STATS40:
            try:
                feat40 = base_raw[:23].copy()  # 40d模型只用前23个基础特征
                # feat40[20..22]已有真实ep/bp/ln_cap来自compute_raw_features()
                # 标准化23个基础特征
                for j in range(23):
                    key = f'feat_{j}'
                    if key in _V9_STATS40:
                        m, s = _V9_STATS40[key]['mean'], _V9_STATS40[key]['std']
                        if s > 0:
                            feat40[j] = max(feat40[j], _V9_STATS40[key]['low'])
                            feat40[j] = min(feat40[j], _V9_STATS40[key]['high'])
                            feat40[j] = (feat40[j] - m) / s
                # 追加GTJA因子（同get_gtja_signals的5天回退逻辑）
                gtja_v = get_gtja_signals(code, dt_str, _V4_GTJA) if _V4_GTJA is not None else []
                feat40 = np.append(feat40, np.array(gtja_v, dtype=np.float64))
                feat40 = np.nan_to_num(feat40.reshape(1,-1), nan=0.0)
                reg40_p = float(_V9_REG40.predict(feat40)[0])
            except Exception as e:
                print(f"v9 predict error for {code}: {e}")
        reg40_score = max(0, min(100, (reg40_p + 10) / 50 * 100))
        
        # 10日模型预测
        reg10_p = 0
        if _USE_V9 and _V10_REG is not None and _V10_STATS:
            try:
                import numpy as np
                feat10 = base_raw.copy()
                for j in range(26):
                    key = f'feat_{j}'
                    if key in _V10_STATS and _V10_STATS[key]['std'] > 0:
                        s = _V10_STATS[key]
                        feat10[j] = max(feat10[j], s['low'])
                        feat10[j] = min(feat10[j], s['high'])
                        feat10[j] = (feat10[j] - s['mean']) / s['std']
                gtja_v = get_gtja_signals(code, dt_str, _V4_GTJA) if _V4_GTJA is not None else []
                feat10 = np.append(feat10, np.array(gtja_v, dtype=np.float64))
                feat10 = np.nan_to_num(feat10.reshape(1,-1), nan=0.0)
                reg10_p = float(_V10_REG.predict(feat10)[0])
            except: pass
        
        reg10_score = max(0, min(100, (reg10_p * 100 + 10) / 50 * 100)) if _V10_REG is not None else 0
        fusion_v9 = min(100, fusion * 0.10 + reg40_score * 0.80 + reg10_score * 0.10) if _USE_V9 else fusion
        
        return (reg_p, lstm_s, fusion, fusion_v9, reg40_p, reg40_score, reg10_p)
    except:
        return None

# ── 账户管理 ──────────────────────────────────────────

def load_account():
    if ACCT_PATH.exists():
        return json.loads(ACCT_PATH.read_text(encoding='utf-8'))
    return None

def save_account(acct):
    ACCT_PATH.write_text(json.dumps(acct, ensure_ascii=False, indent=2), encoding='utf-8')

def create_account():
    return {
        "initial_capital": 1000000.0,
        "cash": 1000000.0,
        "positions": [],
        "trades": [],
        "nav_history": [],
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

_global_db = None
_global_db_ts = 0  # 上次使用时间戳
_DB_MAX_IDLE = 120  # 空闲120秒后自动关闭连接，释放锁

def get_db():
    global _global_db, _global_db_ts
    import duckdb
    now = datetime.now()
    now_ts = now.timestamp()
    
    # 每日数据更新窗口（15:55~16:05）：强制关闭全局连接，释放写锁
    # 否则 dashboard 自动刷新会不断重置空闲计时器，锁永不释放
    in_update_window = (now.hour == 15 and now.minute >= 55) or (now.hour == 16 and now.minute < 5)
    if in_update_window:
        if _global_db is not None:
            try: _global_db.close()
            except: pass
            _global_db = None
        db = duckdb.connect(str(DB_PATH), read_only=True)
        _global_db_ts = now_ts
        return db  # 不缓存，调用者用完即释放
    
    # 检查现有连接是否过期
    if _global_db is not None:
        idle = now_ts - _global_db_ts
        # 收盘后加速释放（15:00后空闲30秒就关）
        max_idle = 30 if now.hour >= 15 or now.hour < 9 else _DB_MAX_IDLE
        if idle > max_idle:
            try: _global_db.close()
            except: pass
            _global_db = None
    
    if _global_db is None:
        _global_db = duckdb.connect(str(DB_PATH), read_only=True)
    
    _global_db_ts = now_ts
    return _global_db

# ── 价格获取 ──────────────────────────────────────────

def fetch_close_from_db(code):
    """从 stock_daily 获取最新收盘价"""
    try:
        db = get_db()
        r = db.execute(f"SELECT date, close FROM stock_daily WHERE stock_code='{code}' ORDER BY date DESC LIMIT 1").fetchone()
        if r:
            return r[0].isoformat() if hasattr(r[0], 'isoformat') else str(r[0]), float(r[1])
        return None, None
    except:
        return None, None

def sina_code(code):
    return f"sh{code}" if code.startswith(('6','68','9')) else f"sz{code}"

# 指数代码前缀映射（sina_code 的 0/3→sz 规则对指数无效）
INDEX_SINA = {'000001': 'sh000001', '399001': 'sz399001', '399006': 'sz399006'}

# 实时价格缓存（30秒有效期，减少新浪API调用）
_price_cache = {}
_PRICE_CACHE_TTL = 30

# API响应缓存（5秒有效期，返回主页时避免重复新浪请求）
_api_cache = {}
_API_CACHE_TTL = 5

def get_api_cache(key):
    now = datetime.now().timestamp()
    cached = _api_cache.get(key)
    if cached and (now - cached['ts']) < _API_CACHE_TTL:
        return cached['data']
    return None

def set_api_cache(key, data):
    _api_cache[key] = {'data': data, 'ts': datetime.now().timestamp()}

def fetch_price_live(code):
    """从 Sina 获取实时价格（带缓存）"""
    now = datetime.now().timestamp()
    cached = _price_cache.get(code)
    if cached and (now - cached['ts']) < _PRICE_CACHE_TTL:
        return cached['price'], cached['prev']
    
    try:
        sina_code_str = INDEX_SINA.get(code) or sina_code(code)
        url = f"https://hq.sinajs.cn/list={sina_code_str}"
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
        raw = urllib.request.urlopen(req, timeout=5).read().decode('gbk')
        if '=""' in raw:
            return None, None
        parts = raw.split('"')[1].split(',')
        price = float(parts[3]) if parts[3] else None
        prev = float(parts[2]) if parts[2] else None
        _price_cache[code] = {'price': price, 'prev': prev, 'ts': now}
        return price, prev
    except:
        return None, None

def fetch_prices_batch(codes):
    """批量获取实时价格 —— 优先pytdx通达信，fallback到新浪"""
    now = datetime.now().timestamp()
    result = {}
    need = []
    for code in codes:
        cached = _price_cache.get(code)
        if cached and (now - cached['ts']) < _PRICE_CACHE_TTL:
            result[code] = cached['price']
        else:
            need.append(code)
    if not need:
        return result

    # ── pytdx通达信行情（毫秒级，非交易时段也能跑）──
    try:
        from pytdx.hq import TdxHq_API
        api = TdxHq_API(heartbeat=False)
        api.connect('180.153.18.172', 80, time_out=3)
        # market: 1=上海, 0=深圳
        multi = [(1, c) if c.startswith(('6','68','9')) else (0, c) for c in need]
        tdx_data = api.get_security_quotes_multi(multi)
        api.disconnect()
        if tdx_data:
            for r in tdx_data:
                code = r['code']
                price = float(r['price'])
                prev = float(r['last_close'])
                if code in need and price > 0:
                    result[code] = price
                    _price_cache[code] = {'price': price, 'prev': prev, 'ts': now}
                    need.remove(code)
    except:
        pass

    # ── 新浪API fallback ──
    if need:
        try:
            sina_codes = ','.join(INDEX_SINA.get(c) or sina_code(c) for c in need)
            url = f"https://hq.sinajs.cn/list={sina_codes}"
            req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
            raw = urllib.request.urlopen(req, timeout=5).read().decode('gbk')
            for line in raw.strip().split('\n'):
                if '=""' in line or 'hq_str_' not in line:
                    continue
                scode = line.split('hq_str_')[1].split('=')[0]
                parts = line.split('"')[1].split(',')
                price = float(parts[3]) if parts[3] else None
                prev = float(parts[2]) if parts[2] else None
                for c in need:
                    if (INDEX_SINA.get(c) or sina_code(c)) == scode:
                        if price is not None:
                            result[c] = price
                            _price_cache[c] = {'price': price, 'prev': prev, 'ts': now}
                        break
        except:
            pass

    return result

def fetch_price(code):
    """获取价格：优先实时，fallback 到 DB"""
    price, prev = fetch_price_live(code)
    if price:
        return price, prev
    _, close = fetch_close_from_db(code)
    return close, close

def get_price_dict(codes):
    """批量获取价格，返回 {code: price}"""
    result = {}
    for code in codes:
        price, _ = fetch_price(code)
        if price:
            result[code] = price
    return result

# ── DB 查询 ──────────────────────────────────────────

def get_recent_close(code, days=60):
    """获取最近 N 个交易日的收盘价"""
    try:
        db = get_db()
        rows = db.execute(f"""
            SELECT date, close FROM stock_daily 
            WHERE stock_code='{code}' 
            ORDER BY date DESC LIMIT {days}
        """).fetchall()
 
        return [(r[0].isoformat() if hasattr(r[0], 'isoformat') else str(r[0]), float(r[1])) for r in rows]
    except:
        return []

def get_stock_daily_detail(code, start_date=None, limit=120):
    """获取个股详细日线数据（单SQL查询+窗口函数）"""
    try:
        db = get_db()
        where = f"AND s.date>='{start_date}'" if start_date else ""
        rows = db.execute(f"""
            SELECT s.date, s.close, s.open, s.high, s.low, s.change_pct, s.volume, s.amount,
                   mf.main_net,
                   AVG(s.close) OVER w5  AS ma5,
                   AVG(s.close) OVER w10 AS ma10,
                   AVG(s.close) OVER w20 AS ma20,
                   AVG(s.close) OVER w60 AS ma60,
                   AVG(s.close) OVER w120 AS ma120,
                   AVG(s.volume) OVER w20 AS avg_vol_20
            FROM stock_daily s
            LEFT JOIN money_flow mf ON s.stock_code=mf.stock_code AND s.date=mf.date
            WHERE s.stock_code='{code}' {where}
            WINDOW w5  AS (ORDER BY s.date ROWS BETWEEN 4  PRECEDING AND CURRENT ROW),
                   w10 AS (ORDER BY s.date ROWS BETWEEN 9  PRECEDING AND CURRENT ROW),
                   w20 AS (ORDER BY s.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
                   w60 AS (ORDER BY s.date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW),
                   w120 AS (ORDER BY s.date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW)
            ORDER BY s.date DESC LIMIT {limit}
        """).fetchall()

        # 获取股票名称（单独查询，极小开销）
        info = db.execute(f"SELECT stock_name FROM stock_info WHERE stock_code='{code}'").fetchone()
        stock_name = info[0] if info else ''

        rows = list(reversed(rows))
        result = []
        prev_close = None
        for r in rows:
            d = r[0].isoformat() if hasattr(r[0], 'isoformat') else str(r[0])
            close = float(r[1]) if r[1] else 0
            # 用前后收盘价计算涨跌幅（DB的change_pct有数据缺失）
            if prev_close and prev_close > 0:
                change_pct = round((close / prev_close - 1) * 100, 2)
            else:
                chg_raw = float(r[5]) if r[5] else 0
                change_pct = round(chg_raw, 2)
            prev_close = close
            item = {
                "date": d,
                "close": close,
                "open": float(r[2]) if r[2] else 0,
                "high": float(r[3]) if r[3] else 0,
                "low": float(r[4]) if r[4] else 0,
                "change_pct": change_pct,
                "volume": float(r[6]) if r[6] else 0,
                "amount": float(r[7]) if r[7] else 0,
                "money_flow": float(r[8]) if r[8] else None,
                "ma5": round(float(r[9]), 2) if r[9] else None,
                "ma10": round(float(r[10]), 2) if r[10] else None,
                "ma20": round(float(r[11]), 2) if r[11] else None,
                "ma60": round(float(r[12]), 2) if r[12] else None,
                "ma120": round(float(r[13]), 2) if r[13] else None,
            }
            # 量比
            avg_v = r[14]
            item['volume_ratio'] = round(item['volume'] / float(avg_v), 2) if avg_v and float(avg_v) > 0 else None

            result.append(item)

        # 给最近30天生成即时分析点评
        analysis_start = max(0, len(result) - 30)
        for i in range(analysis_start, len(result)):
            prev = result[i-1] if i > 0 else None
            result[i]['analysis'] = generate_on_the_fly_analysis(result[i], prev)

        return result, stock_name
    except Exception as e:
        print(f"get_stock_detail error: {e}")
        import traceback; traceback.print_exc()
        return [], ''

def generate_on_the_fly_analysis(snap, prev=None):
    """基于技术指标生成即时详细分析点评（用于详情页）"""
    if not snap:
        return ""
    close = snap.get('close', 0)
    change = snap.get('change_pct', 0)
    vol_ratio = snap.get('volume_ratio')
    mf = snap.get('money_flow')
    ma5 = snap.get('ma5')
    ma10 = snap.get('ma10')
    ma20 = snap.get('ma20')
    ma60 = snap.get('ma60')
    ma120 = snap.get('ma120')
    
    parts = []
    
    # 1. 涨跌方向与幅度
    if change > 5: parts.append(f"🔥暴涨{change:.1f}%")
    elif change > 3: parts.append(f"大涨{change:.1f}%")
    elif change > 1: parts.append(f"上涨{change:.1f}%")
    elif change < -5: parts.append(f"💥暴跌{change:.1f}%")
    elif change < -3: parts.append(f"大跌{change:.1f}%")
    elif change < -1: parts.append(f"下跌{change:.1f}%")
    else: parts.append(f"平盘{change:+.1f}%")
    
    # 2. 量能分析
    if vol_ratio is not None:
        if vol_ratio > 3.0: parts.append(f"巨量(×{vol_ratio:.1f})" + ("🚀" if change > 0 else "💨"))
        elif vol_ratio > 2.0: parts.append(f"放量(×{vol_ratio:.1f})" + ("📈" if change > 0 else "📉"))
        elif vol_ratio > 1.5: parts.append(f"量升(×{vol_ratio:.1f})")
        elif vol_ratio < 0.3: parts.append(f"地量(×{vol_ratio:.1f})💤")
        elif vol_ratio < 0.5: parts.append(f"缩量(×{vol_ratio:.1f})")
        elif vol_ratio < 0.7: parts.append(f"量能不足(×{vol_ratio:.1f})")
    
    # 3. 均线位置分析
    ma_info = []
    if ma5 is not None:
        dev5 = (close - ma5) / ma5 * 100
        if abs(dev5) < 0.5: ma_info.append(f"MA5={ma5:.2f}贴线")
        elif dev5 > 0: ma_info.append(f"MA5={ma5:.2f}上{dev5:.1f}%")
        else: ma_info.append(f"MA5={ma5:.2f}下{abs(dev5):.1f}%")
    if ma20 is not None:
        dev20 = (close - ma20) / ma20 * 100
        if abs(dev20) < 0.5: ma_info.append(f"MA20={ma20:.2f}贴线")
        elif dev20 > 0: ma_info.append(f"MA20={ma20:.2f}上{dev20:.1f}%")
        else: ma_info.append(f"MA20={ma20:.2f}下{abs(dev20):.1f}%")
    
    # MA60/MA120偏差
    if ma60 is not None:
        dev60 = (close - ma60) / ma60 * 100
        if close > ma60: ma_info.append(f"MA60={ma60:.2f}+{abs(dev60):.1f}%")
        else: ma_info.append(f"MA60={ma60:.2f}-{abs(dev60):.1f}%")
    if ma120 is not None:
        dev120 = (close - ma120) / ma120 * 100
        if close > ma120: ma_info.append(f"MA120={ma120:.2f}+{abs(dev120):.1f}%")
        else: ma_info.append(f"MA120={ma120:.2f}-{abs(dev120):.1f}%")
    
    if ma_info:
        parts.append(" | ".join(ma_info))
    
    # 4. 均线排列形态
    if ma5 and ma20 and ma60:
        if ma5 > ma20 > ma60: parts.append("✅多头排列(5>20>60)")
        elif ma5 < ma20 < ma60: parts.append("⚠️空头排列(5<20<60)")
        elif ma5 > ma20 and close > ma5: parts.append("短期偏多(5>20)")
        elif ma5 < ma20 and close < ma5: parts.append("短期偏空(5<20)")
    
    # 5. 资金流
    if mf is not None:
        mf_yi = mf / 100000000
        if mf_yi > 1: parts.append(f"💰主力净流入+{mf_yi:.1f}亿🔥")
        elif mf_yi > 0.3: parts.append(f"主力流入+{mf_yi:.1f}亿")
        elif mf_yi > 0: parts.append(f"主力微流入+{mf_yi:.1f}亿")
        elif mf_yi < -1: parts.append(f"💰主力净流出{mf_yi:.1f}亿💥")
        elif mf_yi < -0.3: parts.append(f"主力流出{mf_yi:.1f}亿")
        else: parts.append(f"主力微流出{mf_yi:.1f}亿")
    
    # 6. 关键信号
    signals = []
    if prev:
        pc = prev.get('close', 0)
        if pc and ma60 and pc < ma60 and close >= ma60: signals.append("突破MA60!✅")
        if pc and ma120 and pc < ma120 and close >= ma120: signals.append("突破MA120!✅")
        if pc and ma60 and pc >= ma60 and close < ma60: signals.append("跌破MA60⚠️")
        if pc and ma120 and pc >= ma120 and close < ma120: signals.append("跌破MA120⚠️")
        # 连涨连跌
        prev_cp = prev.get('change_pct', 0)
        if change > 0 and prev_cp > 0: signals.append("连涨")
        elif change < 0 and prev_cp < 0: signals.append("连跌⚠️")
    
    if vol_ratio is not None and vol_ratio > 2.0 and change > 3: signals.append("放量突破📈")
    if vol_ratio is not None and vol_ratio > 2.0 and change < -3: signals.append("恐慌抛售📉")
    if vol_ratio is not None and vol_ratio < 0.4: signals.append("缩量整理💤")
    
    if signals:
        parts.append(" | ".join(signals))
    
    # 7. 短线判断
    if ma20 and close > ma20 and (mf is None or mf > 0):
        parts.append("短线偏多")
    elif ma20 and close < ma20 and (mf is not None and mf < -0.1):
        parts.append("短线偏空")
    
    return "，".join(parts) if parts else "正常"

# ── 持仓同步 ──────────────────────────────────────────

def sync_from_holdings():
    """从 holdings.json 同步持仓到模拟账户"""
    if not HOLD_PATH.exists():
        return False
    holdings = json.loads(HOLD_PATH.read_text(encoding='utf-8'))
    acct = load_account()
    if not acct:
        acct = create_account()
    
    # 清空旧模拟持仓，从 holdings 重建
    acct['positions'] = []
    
    for p in holdings.get('positions', []):
        code = p['code']
        if p.get('status') == 'hold' and p.get('buy_price'):
            price = p['buy_price']
            # 计算股数：100万 / 持有数 / 股价，取整到100股
            hold_count = sum(1 for x in holdings.get('positions', []) if x.get('status') == 'hold')
            invest_per = acct['initial_capital'] * 0.8 / max(hold_count, 1)
            shares = int(invest_per / price / 100) * 100
            if shares > 0:
                cost = round(shares * price, 2)
                fee = round(cost * 0.001, 2)
                acct['positions'].append({
                    "code": code,
                    "name": p.get('name', ''),
                    "shares": shares,
                    "avg_cost": price,
                    "total_cost": round(cost + fee, 2),
                    "buy_date": p.get('buy_date', ''),
                    "stop_loss": p.get('stop_loss'),
                    "target": p.get('target'),
                })
    
    # 计算现金
    total_invest = sum(p['total_cost'] for p in acct['positions'])
    acct['cash'] = round(acct['initial_capital'] - total_invest, 2)
    
    # 初始净值
    now = datetime.now().strftime("%Y-%m-%d")
    acct['nav_history'] = [{"date": now, "nav": acct['initial_capital'], "cash": acct['cash']}]
    acct['updated_at'] = now
    
    save_account(acct)
    return True

def calc_nav(acct, price_map):
    """计算当前净值"""
    pos_value = 0.0
    for p in acct.get('positions', []):
        code = p['code']
        price = price_map.get(code, 0)
        pos_value += price * p['shares']
    return round(acct.get('cash', 0) + pos_value, 2), round(pos_value, 2)

# ── 交易执行 ──────────────────────────────────────────

def do_buy(acct, code, name, price, shares=None, entry_low=None, entry_high=None, stop_loss=None, target=None):
    """模拟买入"""
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 检查是否已有持仓
    existing = next((p for p in acct['positions'] if p['code'] == code), None)
    if existing:
        # 补仓
        old_shares = existing['shares']
        old_cost = existing['total_cost']
        new_shares = min(shares or 100, int(acct['cash'] / price / 100) * 100)
        if new_shares < 100:
            return False, "现金不足或数量不足100股"
        amount = round(new_shares * price, 2)
        fee = round(amount * 0.001, 2)
        total_shares = old_shares + new_shares
        total_cost = old_cost + amount + fee
        existing['shares'] = total_shares
        existing['avg_cost'] = round(total_cost / total_shares, 2)
        existing['total_cost'] = round(total_cost, 2)
        acct['cash'] = round(acct['cash'] - amount - fee, 2)
        
        now_str = datetime.now().strftime('%H:%M:%S')
        add_name = existing.get('name', code)
        acct['trades'].append({
            "date": today, "time": now_str, "code": code, "action": "add",
            "price": price, "shares": new_shares, "amount": round(amount + fee, 2),
            "cash_before": round(acct['cash'] + amount + fee, 2), "cash_after": acct['cash'],
            "name": add_name,
        })
        add_trade_log('补仓', code, add_name, price, new_shares, reason='',
                      log_date=f"{today} {now_str}")
        return True, f"补仓 {code} {new_shares}股 @{price}"
    
    # 新买入
    avail_cash = acct.get('cash', 0)
    if not shares:
        max_shares = int(avail_cash / price / 100) * 100
        shares = min(max_shares, 5000)  # 单次最多5000股
    shares = max(shares, 100)
    
    amount = round(shares * price, 2)
    fee = round(amount * 0.001, 2)
    total = amount + fee
    
    if total > avail_cash:
        # 调整数量
        shares = int((avail_cash * 0.99) / price / 100) * 100
        if shares < 100:
            return False, "现金不足"
        amount = round(shares * price, 2)
        fee = round(amount * 0.001, 2)
        total = amount + fee
    
    acct['cash'] = round(acct['cash'] - total, 2)
    acct['positions'].append({
        "code": code,
        "name": name,
        "shares": shares,
        "avg_cost": price,
        "total_cost": round(total, 2),
        "buy_date": today,
        "stop_loss": stop_loss,
        "target": target,
    })
    
    now_str = datetime.now().strftime('%H:%M:%S')
    acct['trades'].append({
        "date": today, "time": now_str, "code": code, "action": "buy",
        "price": price, "shares": shares, "amount": round(total, 2),
        "cash_before": round(acct['cash'] + total, 2), "cash_after": acct['cash'],
        "name": name,
    })
    add_trade_log('买入', code, name, price, shares, reason='', log_date=f"{today} {now_str}")
    
    return True, f"买入 {code} {shares}股 @{price}"

def do_sell(acct, code, price=None, shares=None):
    """模拟卖出（shares=None=全仓，否则卖指定股数）"""
    pos = next((p for p in acct['positions'] if p['code'] == code), None)
    if not pos:
        return False, "未持仓"
    
    sell_shares = shares if shares and shares < pos['shares'] else pos['shares']
    remaining = pos['shares'] - sell_shares
    
    today = datetime.now().strftime("%Y-%m-%d")
    if not price:
        price, _ = fetch_price(code)
        if not price:
            return False, "无法获取价格"
        # 价格校验：自动获取的价格不能偏离成本价超过50%（防收盘后取到垃圾数据）
        if pos['avg_cost'] > 0:
            dev = abs(price / pos['avg_cost'] - 1) * 100
            if dev > 50:
                return False, f"价格异常: {price:.2f} 偏离成本{pos['avg_cost']:.2f} {dev:.0f}%，拒绝自动卖出"
    
    amount = round(price * sell_shares, 2)
    fee = round(amount * 0.001, 2)
    cost_part = round(pos['total_cost'] * (sell_shares / pos['shares']), 2)
    pnl = round(amount - fee - cost_part, 2)
    pnl_pct = round(pnl / cost_part * 100, 2) if cost_part > 0 else 0
    
    acct['cash'] = round(acct['cash'] + amount - fee, 2)
    
    now_str = datetime.now().strftime('%H:%M:%S')
    name = pos.get('name', code)
    acct['trades'].append({
        "date": today, "time": now_str, "code": code, "action": "sell",
        "price": price, "shares": sell_shares, "amount": round(amount - fee, 2),
        "pnl": pnl, "pnl_pct": pnl_pct,
        "cash_before": round(acct['cash'] - amount + fee, 2), "cash_after": acct['cash'],
        "name": name,
    })
    add_trade_log('卖出', code, name, price, sell_shares, reason='', pnl=pnl_pct, log_date=f"{today} {now_str}")
    
    if remaining > 0:
        # 部分卖出，更新剩余仓位
        pos['shares'] = remaining
        pos['total_cost'] = round(pos['total_cost'] - cost_part, 2)
        pos['avg_cost'] = round(pos['total_cost'] / remaining, 2)
    else:
        acct['positions'].remove(pos)
    
    return True, f"卖出 {code} {sell_shares}股 @{price} (盈亏:{pnl_pct}%)"

# ── 信号集成 ──────────────────────────────────────────

def run_fupan():
    """运行复盘.py 获取候选"""
    try:
        fupan_py = SCRIPTS / '复盘.py'
        if not fupan_py.exists():
            return []
        result = subprocess.run(
            [sys.executable, str(fupan_py), '--mode', 'long'],
            capture_output=True, text=True, timeout=60,
            cwd=str(SCRIPTS),
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        )
        output = result.stdout + result.stderr
        # 尝试从输出提取候选股票代码 (复盘.py 的输出格式)
        candidates = re.findall(r'(\d{6})\s+', output)
        return list(set(candidates))
    except:
        return []

def run_scoring(code, mode='long'):
    """运行 scoring.py 对单只股票评分"""
    try:
        scoring_py = SCRIPTS / 'scoring.py'
        if not scoring_py.exists():
            return None, None
        result = subprocess.run(
            [sys.executable, str(scoring_py), code, '--mode', mode],
            capture_output=True, text=True, timeout=30,
            cwd=str(SCRIPTS),
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        )
        output = result.stdout + result.stderr
        # 提取总分，格式如 "总分 82.5/100"
        score_match = re.search(r'总分\s*([\d.]+)', output)
        score = float(score_match.group(1)) if score_match else None
        return score, output
    except:
        return None, None

def refresh_signals():
    """刷新信号：运行复盘+评分"""
    candidates = run_fupan()
    signals = []
    for code in candidates:
        score, detail = run_scoring(code)
        price, _ = fetch_price(code)
        if score:
            signals.append({"code": code, "score": round(score, 1), "price": price})
    signals.sort(key=lambda x: x['score'], reverse=True)
    return signals

# 个股分析缓存（120秒有效，避免重复新浪请求+DB查询）
# ── 交易日志（内存，供首页显示） ──
_trade_log = []      # [{time, date, action, code, name, price, shares, reason, pnl}]
_trade_log_lock = threading.Lock()

def add_trade_log(action, code, name, price, shares, reason='', pnl=None, log_date=None):
    """log_date: None=用当前时间, str('YYYY-MM-DD')=只有日期(历史恢复), str('YYYY-MM-DD HH:MM:SS')=完整时间, datetime=精确时间"""
    if log_date is None:
        dt = datetime.now()
        _time = dt.strftime('%H:%M:%S')
    elif isinstance(log_date, datetime):
        dt = log_date
        _time = dt.strftime('%H:%M:%S')
    elif len(str(log_date)) > 10:
        # 完整日期时间 "2026-06-02 15:36:22"
        dt = datetime.strptime(str(log_date)[:19], '%Y-%m-%d %H:%M:%S')
        _time = dt.strftime('%H:%M:%S')
    else:
        # 只有日期，没有时间 → 旧记录
        dt = datetime.strptime(str(log_date)[:10], '%Y-%m-%d')
        _time = ''
    with _trade_log_lock:
        _trade_log.append({
            'time': _time,
            'date': dt.strftime('%m-%d'),
            'action': action, 'code': code, 'name': name,
            'price': price, 'shares': shares, 'amount': round(price * shares, 2),
            'reason': reason, 'pnl': pnl,
        })
        if len(_trade_log) > 100:
            _trade_log[:] = _trade_log[-50:]

# ── QQ通知：写入 pending_alerts.json，由 cron 发送 ──
ALERT_PATH = os.path.join(os.path.dirname(ACCT_PATH) or os.path.expanduser('~/.hermes/stockdb'), 'pending_alerts.json')
_alert_lock = threading.Lock()

def _append_alert(action, code, name, price, shares, reason='', pnl=None):
    try:
        now = datetime.now()
        entry = {
            'ts': now.strftime('%Y-%m-%d %H:%M:%S'),
            'time': now.strftime('%m-%d %H:%M'),
            'action': action, 'code': code, 'name': name,
            'price': round(price, 2), 'shares': shares,
            'reason': reason,
        }
        if pnl is not None:
            entry['pnl'] = round(pnl, 2)
        with _alert_lock:
            alerts = []
            if os.path.exists(ALERT_PATH):
                try:
                    with open(ALERT_PATH) as f:
                        alerts = json.load(f)
                except: pass
            alerts.append(entry)
            # 最多保留10条
            if len(alerts) > 10:
                alerts = alerts[-10:]
            with open(ALERT_PATH, 'w') as f:
                json.dump(alerts, f)
    except: pass

def _lookup_name(code):
    """从 stock_info 表查股票名称"""
    try:
        import duckdb
        _db = duckdb.connect(str(BASE / 'stock.db'), read_only=True)
        _r = _db.execute(f"SELECT stock_name FROM stock_info WHERE stock_code='{code}'").fetchone()
        _db.close()
        return _r[0] if _r and _r[0] else code
    except:
        return code

# 启动时从账户流水恢复交易日志
def _restore_trade_log():
    try:
        acct = json.loads(ACCT_PATH.read_text(encoding='utf-8'))
        for t in reversed(acct.get('trades', [])[-50:]):
            act = '买入' if t['action'] == 'buy' else ('卖出' if t['action'] == 'sell' else '补仓')
            pnl = t.get('pnl_pct')
            trade_date = t.get('date')
            trade_time = t.get('time')
            name = t.get('name', '')
            if not name:
                name = _lookup_name(t['code'])
            if trade_time:
                log_date = f"{trade_date} {trade_time}"
            else:
                log_date = trade_date  # 旧记录只有日期
            add_trade_log(act, t['code'], name, t['price'], t['shares'],
                          reason=f"", pnl=pnl, log_date=log_date)
    except: pass

_restore_trade_log()

def get_trade_log():
    with _trade_log_lock:
        return list(reversed(_trade_log))

# ── 实时价格监控（独立后台线程） ──
_price_alerts = {}
_price_alerts_lock = threading.Lock()
_MONITOR_INTERVAL = 15

def _price_monitor_thread():
    """后台线程：每15秒查新浪，检测观察股是否到价"""
    while True:
        try:
            threading.Event().wait(_MONITOR_INTERVAL)
            if not HOLD_PATH.exists(): continue
            data = json.loads(HOLD_PATH.read_text(encoding='utf-8'))
            watch = [p for p in data.get('positions', [])
                     if p.get('status') in ('watch_active',) and p.get('entry_low') and p.get('entry_high')]
            if not watch: continue
            codes = [p['code'] for p in watch]
            prices = fetch_prices_batch(codes)
            with _price_alerts_lock:
                for p in watch:
                    code = p['code']
                    price = prices.get(code)
                    if not price: continue
                    el, eh = p['entry_low'], p['entry_high']
                    old = _price_alerts.get(code, {})
                    was_trig = old.get('triggered', False)
                    in_range = el <= price <= eh
                    _price_alerts[code] = {
                        'price': price, 'entry_low': el, 'entry_high': eh,
                        'name': p.get('name', code),
                        'triggered': in_range,
                        'new_trigger': in_range and not was_trig,
                        'time': datetime.now().strftime('%H:%M:%S'),
                    }
                    # 自动买入（新到价且非交易时段外）
                    if in_range and not was_trig:
                        current_hour = datetime.now().hour
                        if 9 <= current_hour <= 15:
                            try:
                                acct = load_account()
                                if not acct: continue
                                # 防重复：检查 account.json 是否已持仓
                                if any(pos['code'] == code for pos in acct.get('positions', [])):
                                    continue
                                # 趋势检查：5日均价 > 10日均价（不在下跌趋势中追买）
                                try:
                                    db2 = get_db()
                                    cls = db2.execute(f"""
                                        SELECT close FROM stock_daily WHERE stock_code='{code}' 
                                        ORDER BY date DESC LIMIT 12
                                    """).fetchall()
                                    if len(cls) >= 10:
                                        c = [float(r[0]) for r in cls][::-1]
                                        ma5 = sum(c[-5:])/5; ma10 = sum(c[-10:])/10
                                        if ma5 <= ma10:
                                            continue  # 下跌趋势，不追
                                except: pass
                                # 计算仓位（等权：当前现金 ÷ 剩余观察仓位）
                                remaining = sum(1 for wp in watch if wp['code'] != code and not _price_alerts.get(wp['code'], {}).get('triggered', False))
                                pos_cash = acct['cash'] / max(remaining + 1, 1)
                                shares = int(pos_cash / price / 100) * 100
                                if shares < 100: continue
                                ok, msg = do_buy(acct, code, p.get('name', code), price,
                                                 shares=shares, entry_low=el, entry_high=eh,
                                                 stop_loss=p.get('stop_loss'), target=p.get('target'))
                                if ok:
                                    save_account(acct)
                                    # 更新holdings状态（同一个code的所有记录都改）
                                    data = json.loads(HOLD_PATH.read_text(encoding='utf-8'))
                                    for pos in data.get('positions', []):
                                        if pos['code'] == code and pos.get('status') != 'archived':
                                            pos['status'] = 'hold'
                                            pos['buy_date'] = datetime.now().strftime('%Y-%m-%d')
                                            pos['buy_price'] = price
                                    with open(HOLD_PATH, 'w', encoding='utf-8') as f:
                                        json.dump(data, f, ensure_ascii=False, indent=2)
                                    print(f"[AUTO] 买入 {code} {p.get('name','')} x{shares} @ {price:.2f}")
                                    add_trade_log('买入', code, p.get('name',code), price, shares,
                                                  reason=f'进区间{el}~{eh}')
                                    # QQ通知
                                    _append_alert('买入', code, p.get('name',code), price, shares, f'进区间{el}~{eh}')
                                    _price_alerts[code]['bought'] = True
                            except: pass
        except: pass

        # ── 自动卖出（持仓风控） ──
        try:
            acct = load_account()
            if acct and acct.get('positions'):
                pos_codes = [p['code'] for p in acct['positions']]
                pos_prices = fetch_prices_batch(pos_codes)
                for pos in list(acct['positions']):
                    code = pos['code']
                    price = pos_prices.get(code)
                    if not price: continue
                    sl = pos.get('stop_loss')
                    tg = pos.get('target')
                    cost = pos.get('avg_cost', price)
                    pnl_pct = (price/cost - 1) * 100
                    
                    # 最短持有期：5天内只响应硬止损(-8%)
                    buy_date = pos.get('buy_date', '')
                    hold_days = 999
                    if buy_date:
                        try:
                            bd = datetime.strptime(str(buy_date)[:10], '%Y-%m-%d')
                            hold_days = (datetime.now() - bd).days
                        except: pass
                    
                    # 防双重执行：检查 risk_signals.json 是否今天已处理
                    skip_for_risk = False
                    try:
                        sig_path = BASE / 'risk_signals.json'
                        if sig_path.exists():
                            sig_data = json.loads(sig_path.read_text())
                            for sig in sig_data.get('signals', []):
                                if sig['code'] == code and sig.get('action') in ('清仓','减半仓'):
                                    skip_for_risk = True
                                    break
                    except: pass
                    
                    reason = None
                    # T+1：今天买的不能卖（保持）
                    if buy_date == datetime.now().strftime('%Y-%m-%d'):
                        continue
                    
                    # 硬止损（任何时候都执行）
                    if sl and price <= sl:
                        reason = f'止损 {price:.2f}<={sl:.2f}'
                    elif pnl_pct <= -12:
                        reason = f'硬止损 {pnl_pct:.1f}%'
                    # 达目标（5天后执行，除非盈利>15%）
                    elif tg and price >= tg and (hold_days >= 5 or pnl_pct >= 15):
                        reason = f'达目标 {price:.2f}>={tg:.2f}'
                    
                    # 最短持有期内跳过非硬止损的卖出
                    if reason and hold_days < 5 and '止损' not in reason and '硬止损' not in reason:
                        continue
                    
                    # 风险信号已覆盖，跳过
                    if reason and skip_for_risk and '硬止损' not in reason:
                        continue
                    if reason:
                        ok, msg = do_sell(acct, code, price)
                        if ok:
                            save_account(acct)
                            hdata = json.loads(HOLD_PATH.read_text(encoding='utf-8'))
                            for hp in hdata.get('positions', []):
                                if hp['code'] == code and hp.get('status') != 'archived':
                                    hp['status'] = 'archived'
                                    hp['archive_reason'] = f'自动平仓 {reason}'
                                    hp['sell_price'] = price
                                    hp['pnl_pct'] = round((price - pos.get('avg_cost',price)) / pos.get('avg_cost',price) * 100, 2)
                                    break
                            with open(HOLD_PATH, 'w', encoding='utf-8') as f:
                                json.dump(hdata, f, ensure_ascii=False, indent=2)
                            print(f"[AUTO] 卖出 {code} {pos.get('name','')} x{pos['shares']} @ {price:.2f} ({reason})")
                            pnl_pct = round((price - pos.get('avg_cost',price)) / pos.get('avg_cost',price) * 100, 2)
                            add_trade_log('卖出', code, pos.get('name',code), price, pos['shares'],
                                          reason=reason, pnl=pnl_pct)
                            # QQ通知
                            _append_alert('卖出', code, pos.get('name',code), price, pos['shares'], reason, pnl=pnl_pct)
        except: pass

def get_price_alerts():
    with _price_alerts_lock:
        return dict(_price_alerts)

# ── 个股分析缓存 ──
_analyze_cache = {}
_ANALYZE_CACHE_TTL = 120

def analyze_stock(code, daily_data=None):
    """手动分析单只股票：技术面+资金面+均线系统
    可传入 daily_data 复用已查数据，避免重复DB查询"""
    now = datetime.now().timestamp()
    cached = _analyze_cache.get(code)
    if cached and (now - cached['ts']) < _ANALYZE_CACHE_TTL:
        return cached['data']

    # 始终获取实时价格（fetch_price内部5秒缓存，Sina超时自动fallback到DB）
    price, prev_close = fetch_price(code)

    result = {
        "code": code, "name": "", "price": price, "prev_close": prev_close,
        "score": None, "score_detail": {}, "analysis": "", "report_lines": [],
    }

    try:
        db = get_db()
        nr = db.execute(f"SELECT stock_name FROM stock_info WHERE stock_code='{code}'").fetchone()
        result['name'] = nr[0] if nr else ''

        # 复用 daily_data（时间升序）或从DB查
        if daily_data:
            rows = [(r['date'],
                     r['close'], r['open'], r['high'], r['low'],
                     r['change_pct'], r['volume'], r['amount'])
                    for r in reversed(daily_data)]  # 转成时间降序
            today_str = daily_data[-1]['date']
            close_proxy = daily_data[-1]['close']
        else:
            rows = db.execute(f"""
                SELECT date, close, open, high, low, change_pct, volume, amount
                FROM stock_daily WHERE stock_code='{code}'
                ORDER BY date DESC LIMIT 120
            """).fetchall()
            today_str = str(rows[0][0]) if rows else ''
            close_proxy = float(rows[0][1]) if rows else 0

        if not rows:
            result['analysis'] = '⚠️ 无日线数据'
            return result

        closes = [float(r[1]) for r in rows if r[1]]
        vols = [float(r[6]) for r in rows if r[6]]
        latest = rows[0]
        close = price if price else close_proxy
        change = ((close / prev_close) - 1) * 100 if prev_close and prev_close > 0 else (float(latest[5]) if latest[5] else 0)
        volume = float(latest[6]) if latest[6] else 0
        amount = float(latest[7]) if latest[7] else 0
        
        # 计算均线
        ma5 = sum(closes[:5]) / 5 if len(closes) >= 5 else None
        ma10 = sum(closes[:10]) / 10 if len(closes) >= 10 else None
        ma20 = sum(closes[:20]) / 20 if len(closes) >= 20 else None
        ma60 = sum(closes[:60]) / 60 if len(closes) >= 60 else None
        ma120 = sum(closes[:120]) / 120 if len(closes) >= 120 else sum(closes) / len(closes) if closes else None
        
        # 量比
        avg_vol_20 = sum(vols[:20]) / min(20, len(vols)) if vols else 1
        vol_ratio = round(volume / avg_vol_20, 2) if avg_vol_20 > 0 else None
        
        # 资金流
        if daily_data:
            # 从 daily_data 取最新和30日累计
            money_flow = daily_data[-1].get('money_flow')
            mf_vals = [r.get('money_flow') or 0 for r in daily_data[-30:]]
            money_flow_30d = sum(mf_vals)
        else:
            mf_row = db.execute(f"SELECT main_net FROM money_flow WHERE stock_code='{code}' AND date='{today_str}'").fetchone()
            money_flow = float(mf_row[0]) if mf_row and mf_row[0] else None
            mf30 = db.execute(f"SELECT SUM(main_net) FROM money_flow WHERE stock_code='{code}' AND date>='{rows[-1][0]}'").fetchone()
            money_flow_30d = float(mf30[0]) if mf30 and mf30[0] else None
        
        # 60日涨幅
        chg60 = (close / closes[min(59, len(closes)-1)] - 1) * 100 if len(closes) >= 60 else None
        
        # 年线偏离度
        dev120 = (close - ma120) / ma120 * 100 if ma120 else None
        
        # 最近5天
        recent = []
        for r in rows[:5]:
            recent.append({
                "date": str(r[0]), "close": float(r[1]) if r[1] else 0,
                "chg": float(r[5]) if r[5] else 0,
            })
        
 
        
        # ── 生成分析报告（复盘风格）──
        lines = []
        lines.append(f"📊 {result['name']}({code}) 技术分析")
        lines.append(f"  现价: {close:.2f}  |  涨跌: {change:+.2f}%  |  量比: {vol_ratio if vol_ratio else '--'}")
        lines.append(f"  成交额: {amount/100000000:.2f}亿  |  60日涨跌: {chg60:+.1f}%" if chg60 else "")
        
        # MA分析
        ma_line = "  均线:"
        if ma5: ma_line += f" MA5={ma5:.2f}({'↑' if close > ma5 else '↓'})"
        if ma10: ma_line += f" MA10={ma10:.2f}({'↑' if close > ma10 else '↓'})"
        if ma20: ma_line += f" MA20={ma20:.2f}({'↑' if close > ma20 else '↓'})"
        if ma60: ma_line += f" MA60={ma60:.2f}({'↑' if close > ma60 else '↓'})"
        if ma120: ma_line += f" MA120={ma120:.2f}({'↑' if close > ma120 else '↓'})"
        lines.append(ma_line)
        
        # 均线排列
        if ma5 and ma20 and ma60:
            if ma5 > ma20 > ma60:
                lines.append("  ✅ 均线多头排列(5>20>60)，趋势向上")
            elif ma5 < ma20 < ma60:
                lines.append("  ⚠️ 均线空头排列(5<20<60)，趋势向下")
            elif ma5 > ma20:
                lines.append("  短期偏多(5>20)")
            else:
                lines.append("  短期偏空(5<20)")
        
        # 年线位置
        if dev120 is not None:
            if abs(dev120) < 3:
                lines.append(f"  贴近年线(MA120={ma120:.2f})，方向选择窗口")
            elif close > ma120 and dev120 < 15:
                lines.append(f"  年线上方{dev120:.1f}%，中期趋势偏多")
            elif close > ma120 and dev120 > 30:
                lines.append(f"  远离年线+{dev120:.0f}%，注意回调风险")
            elif close < ma120:
                lines.append(f"  年线下方{abs(dev120):.1f}%，中期承压")
        
        # 量能分析
        if vol_ratio:
            if vol_ratio > 2.0 and change > 3:
                lines.append(f"  📈 放量上攻(×{vol_ratio:.1f})，资金活跃")
            elif vol_ratio > 2.0 and change < -3:
                lines.append(f"  📉 放量下跌(×{vol_ratio:.1f})，抛压较大")
            elif vol_ratio > 1.5 and change > 0:
                lines.append(f"  量价配合(×{vol_ratio:.1f})，走势健康")
            elif vol_ratio < 0.5:
                lines.append(f"  缩量整理(×{vol_ratio:.1f})，观望情绪浓")
        
        # 资金流
        if money_flow is not None:
            mf_yi = money_flow / 100000000
            lines.append(f"  当日主力资金: {mf_yi:+.2f}亿")
        if money_flow_30d is not None:
            mf30_yi = money_flow_30d / 100000000
            lines.append(f"  近30日主力累计: {mf30_yi:+.2f}亿")
        
        # 近期走势
        if recent:
            trend = "  ".join([f"{r['date'][5:]}{r['close']:.1f}({r['chg']:+.1f}%)" for r in recent])
            lines.append(f"  最近5日: {trend}")
        
        # 综合判断
        bullish = 0
        if ma5 is not None and close > ma5: bullish += 1
        if ma20 is not None and close > ma20: bullish += 1
        if ma60 is not None and close > ma60: bullish += 1
        if ma5 and ma20 and ma5 > ma20: bullish += 1
        if dev120 and close > ma120: bullish += 1
        if money_flow and money_flow > 0: bullish += 1
        if vol_ratio and vol_ratio > 1.2: bullish += 1
        
        if bullish >= 5:
            verdict = "✅ 整体偏多，可关注介入机会"
        elif bullish >= 3:
            verdict = "◻️ 震荡观望，等待明确信号"
        else:
            verdict = "⚠️ 整体偏弱，注意风险"
        lines.append(f"  ───\n  ▶ {verdict} (多空评分 {bullish}/7)")
        
        result['analysis'] = "\n".join(lines)
        result['report_lines'] = lines
        result['score'] = round(bullish / 7 * 100, 1)
        result['score_detail'] = {"多头信号": bullish, "空头信号": 7 - bullish}

        # ── 模型评分（共享 core/scoring.py）──
        try:
            from core.scoring import score_stock, _ensure_models
            _ensure_models()
            db_v6 = get_db()
            rows_sc = db_v6.execute(f"""
                SELECT date, close, open, high, low, change_pct, volume, amount
                FROM stock_daily WHERE stock_code='{code}'
                ORDER BY date DESC LIMIT 120
            """).fetchall()
            if len(rows_sc) >= 120:
                sc_result = score_stock(code, rows_sc)
                if sc_result:
                    result['score'] = sc_result.get('final_score', sc_result['fusion_v9'])
                    result['v9'] = {'fusion': sc_result['fusion_v9'], 'final_score': sc_result.get('final_score'), 'fusion_avg': sc_result.get('fusion_avg')}
                    result['cls27_prob'] = sc_result.get('cls27_prob')
                    result['reg_pred'] = sc_result['reg_pred']
                    result['reg10_pred'] = sc_result.get('reg10_pred')
                    result['reg40_pred'] = sc_result['reg40_pred']
                    model_name = "融合(40d+20d+10d)xcls27"
                    lines.append(f"  ───")
                    final_s = sc_result.get('final_score', sc_result['fusion_v9'])
                    cls_p = sc_result.get('cls27_prob', 0.5)
                    line = f"  🤖 {model_name}评分: {final_s:.0f}分 (cls27置信度:{cls_p:.1%})"
                    line += f"\n        40日预测:{sc_result['reg40_pred']:+.1f}%"
                    if sc_result['reg_pred'] is not None:
                        line += f"  20日预测:{sc_result['reg_pred']:+.1f}%"
                        line += f"\n        10日预测:{sc_result.get('reg10_pred',0):+.1f}%"
                    lines.append(line)
                    result['analysis'] = "\n".join(lines)
            else:
                lines.append(f"  ⓘ 日线不足120天，模型评分不可用")
        except Exception:
            lines.append(f"  ⚠️ 模型评分异常")
        result['analysis'] = "\n".join(lines)
    except Exception as e:
        result['analysis'] = f"⚠️ 分析异常: {e}"
    return result


# ── 净值管理 ──────────────────────────────────────────

def update_nav(acct, price_map):
    """更新净值记录"""
    today = datetime.now().strftime("%Y-%m-%d")
    nav, pos_val = calc_nav(acct, price_map)
    
    # 去重：如果今天已有记录则更新，否则追加
    history = acct.get('nav_history', [])
    existing = next((h for h in history if h['date'] == today), None)
    entry = {"date": today, "nav": nav, "cash": acct.get('cash', 0), "position_value": round(pos_val, 2)}
    if existing:
        existing.update(entry)
    else:
        history.append(entry)
    # 最多保留365条
    if len(history) > 365:
        history = history[-365:]
    acct['nav_history'] = history

# ── HTTP 服务器 ───────────────────────────────────────

PORT = 8080
AUTH_PASSWORD = ""  # 密码已取消
import hashlib, secrets, html

class SimHandler(BaseHTTPRequestHandler):
    
    def _check_auth(self):
        """检查是否已登录（cookie token）"""
        if not AUTH_PASSWORD:
            return True  # 密码为空则不验证
        cookies = self.headers.get('Cookie', '')
        # 查找 session_token cookie
        for c in cookies.split(';'):
            c = c.strip()
            if c.startswith('session_token='):
                token = c.split('=', 1)[1]
                expected = hashlib.sha256(AUTH_PASSWORD.encode()).hexdigest()[:16]
                return token == expected
        return False
    
    def _require_auth(self):
        """未登录返回登录页"""
        if self._check_auth():
            return True
        if self.path.startswith('/static/') or self.path == '/api/login':
            return True  # 静态文件和登录接口不拦截
        self._html(LOGIN_PAGE)
        return False
    
    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        self._last_json = data
    
    def _html(self, html, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    
    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return self.rfile.read(length).decode('utf-8') if length else ''
    
    def do_GET(self):
        if not self._require_auth():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        
        if path == '/':
            self._html(HTML_PAGE)
        
        elif path == '/api/status':
            # 5秒缓存
            cached = get_api_cache('api_status')
            if cached:
                self._json(cached)
                return
            acct = load_account()
            if not acct:
                self._json({"ok": False, "msg": "账户未初始化，请先同步"}, 400)
                return
            codes = [p['code'] for p in acct.get('positions', [])]
            price_map = get_price_dict(codes)
            nav, pos_val = calc_nav(acct, price_map)
            init = acct.get('initial_capital', 1000000)
            total_pnl = round(nav - init, 2)
            total_pnl_pct = round((nav - init) / init * 100, 2)
            
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            
            # 持仓详情
            # 预载holdings数据作为兜底
            _holdings_cache = {}
            if HOLD_PATH.exists():
                try:
                    hd = json.loads(HOLD_PATH.read_text(encoding='utf-8'))
                    for hp in hd.get('positions', []):
                        _holdings_cache[hp['code']] = hp
                except: pass
            
            positions_detail = []
            for p in acct.get('positions', []):
                cp = price_map.get(p['code'])
                if not cp:
                    _, cp_db = fetch_close_from_db(p['code'])
                    cp = cp_db
                pnl = round((cp - p['avg_cost']) / p['avg_cost'] * 100, 2) if cp and p['avg_cost'] else 0
                market_val = round(cp * p['shares'], 2) if cp else 0
                # 从holdings兜底名称/止损/目标
                hp = _holdings_cache.get(p['code'], {})
                name = p.get('name') or hp.get('name', '')
                stop_loss = p.get('stop_loss') or hp.get('stop_loss')
                target = p.get('target') or hp.get('target')
                positions_detail.append({
                    "code": p['code'],
                    "name": name,
                    "shares": p['shares'],
                    "avg_cost": p['avg_cost'],
                    "current_price": cp,
                    "pnl_pct": pnl,
                    "market_value": market_val,
                    "stop_loss": stop_loss,
                    "target": target,
                    "buy_date": p.get('buy_date'),
                })
            
            # 交易统计
            trades = acct.get('trades', [])
            sell_trades = [t for t in trades if t['action'] == 'sell']
            win = sum(1 for t in sell_trades if t.get('pnl', 0) > 0)
            loss = sum(1 for t in sell_trades if t.get('pnl', 0) <= 0)
            win_rate = round(win / max(len(sell_trades), 1) * 100, 1)
            
            # 持仓命中率 = 当前盈利的持仓数 / 总持仓数
            hold_hit = sum(1 for p in positions_detail if p.get('pnl_pct', 0) > 0)
            hold_hit_rate = round(hold_hit / max(len(positions_detail), 1) * 100, 1)
            
            # 批量计算v9评分
            try:
                db_v6 = get_db()
                for p in positions_detail:
                    code = p['code']
                    rows = db_v6.execute(f"""
                        SELECT date, close, open, high, low, change_pct, volume, amount
                        FROM stock_daily WHERE stock_code='{code}'
                        ORDER BY date DESC LIMIT 120
                    """).fetchall()
                    # 使用 core.scoring.score_stock（50/40/10 + cls27）
                    from core.scoring import score_stock as ss_sc
                    sc_r = ss_sc(code, rows)
                    p['v5_score'] = round(sc_r['final_score'], 1) if sc_r else None
                    p['reg_pred'] = round(sc_r['reg_pred'], 1) if sc_r else None
            except: pass
            
            self._json({
                "ok": True,
                "time": now,
                "initial_capital": init,
                "cash": round(acct.get('cash', 0), 2),
                "position_value": round(pos_val, 2),
                "nav": nav,
                "total_pnl": total_pnl,
                "total_pnl_pct": total_pnl_pct,
                "positions": positions_detail,
                "position_count": len(positions_detail),
                "trades_count": len(trades),
                "win_rate": win_rate,
                "win_count": win,
                "loss_count": loss,
                "hold_hit_rate": hold_hit_rate,
                "nav_history": acct.get('nav_history', []),
            })
            set_api_cache('api_status', self._last_json)
        
        elif path == '/api/holdings':
            if HOLD_PATH.exists():
                data = json.loads(HOLD_PATH.read_text(encoding='utf-8'))
                active = [p for p in data.get('positions', [])
                         if p.get('status') in ('hold', 'watch_active', 'watch_cold')]
                
                # 批量计算v5评分
                db = get_db()
                for p in active:
                    code = p['code']
                    rows = db.execute(f"""
                        SELECT date, close, open, high, low, change_pct, volume, amount
                        FROM stock_daily WHERE stock_code='{code}'
                        ORDER BY date DESC LIMIT 120
                        """).fetchall()
                    from core.scoring import score_stock as ss_sc_w
                    sc_r = ss_sc_w(code, rows)
                    p['v5_score'] = round(sc_r['final_score'], 1) if sc_r else None
                    p['reg_pred'] = round(sc_r['reg_pred'], 1) if sc_r else None

                self._json({"positions": active, "total": len(data.get('positions',[])), "active": len(active)})
            else:
                self._json({"positions": []})
        
        elif path == '/api/nav':
            acct = load_account()
            self._json(acct.get('nav_history', []) if acct else [])
        
        elif path == '/api/signals':
            signals = refresh_signals()
            self._json({"ok": True, "signals": signals, "time": datetime.now().strftime("%Y-%m-%d %H:%M")})

        elif path == '/api/price_alerts':
            """实时价格监控警报"""
            self._json({"ok": True, "alerts": get_price_alerts(), "time": datetime.now().strftime("%H:%M:%S")})

        elif path == '/api/trade_log':
            """交易日志（最新50条）"""
            self._json({"ok": True, "trades": get_trade_log()})
        
        elif path == '/api/sync':
            ok = sync_from_holdings()
            self._json({"ok": ok, "msg": "同步成功" if ok else "同步失败"})
        
        elif path == '/api/update_nav':
            acct = load_account()
            if acct:
                codes = [p['code'] for p in acct.get('positions', [])]
                price_map = get_price_dict(codes)
                update_nav(acct, price_map)
                save_account(acct)
                self._json({"ok": True, "msg": "净值已更新"})
            else:
                self._json({"ok": False, "msg": "账户未初始化"})
        
        elif path == '/api/all_accounts':
            """三个系统汇总"""
            try:
                import duckdb
                conn = duckdb.connect(str(DB_PATH), read_only=True)
                accounts = []

                # 1) 中长线
                acct_long = load_account()
                if acct_long:
                    codes_l = [p['code'] for p in acct_long.get('positions', [])]
                    price_map = get_price_dict(codes_l)
                    nav_l, pos_val_l = calc_nav(acct_long, price_map)
                    init_l = acct_long.get('initial_capital', 1_000_000)
                    pos_detail_l = []
                    for p in acct_long.get('positions', []):
                        cp = price_map.get(p['code'])
                        cur = cp or 0
                        cost = p.get('avg_cost', 0)
                        pnl = round((cur / cost - 1) * 100, 2) if cost else 0
                        pos_detail_l.append({
                            "code": p['code'], "name": p.get('name', ''),
                            "shares": p['shares'], "cost": round(cost, 2),
                            "current": cur, "pnl_pct": pnl,
                            "pnl_value": round((cur - cost) * p['shares'], 2),
                        })
                    accounts.append({
                        "name": "中长线", "file": "account.json",
                        "initial_capital": init_l, "cash": round(acct_long.get('cash', 0), 2),
                        "nav": round(nav_l, 2), "pnl_pct": round((nav_l / init_l - 1) * 100, 2),
                        "pnl_value": round(nav_l - init_l, 2),
                        "positions": pos_detail_l, "pos_count": len(pos_detail_l),
                    })

                # 2) 短线
                short_path = BASE / 'short_account.json'
                if short_path.exists():
                    acct_short = json.loads(short_path.read_text(encoding='utf-8'))
                    codes_s = [p['code'] for p in acct_short.get('positions', [])]
                    price_map_s = get_price_dict(codes_s)
                    init_s = acct_short.get('initial_capital', 500_000)
                    pos_val_s, nav_s = 0, acct_short.get('cash', 0)
                    pos_detail_s = []
                    for p in acct_short.get('positions', []):
                        cp = price_map_s.get(p['code'])
                        cur = cp or 0
                        cost = p.get('avg_cost', 0)
                        shares = p.get('shares', 0)
                        mkt = cur * shares
                        pos_val_s += mkt
                        pnl = round((cur / cost - 1) * 100, 2) if cost else 0
                        pos_detail_s.append({
                            "code": p['code'], "name": p.get('name', ''),
                            "shares": shares, "cost": round(cost, 2),
                            "current": cur, "pnl_pct": pnl,
                            "pnl_value": round((cur - cost) * shares, 2),
                        })
                    nav_s = acct_short.get('cash', 0) + pos_val_s
                    hit_s = sum(1 for p in pos_detail_s if p.get('pnl_pct', 0) > 0)
                    hit_rate_s = round(hit_s / max(len(pos_detail_s), 1) * 100, 1)
                    accounts.append({
                        "name": f"短线 ({hit_rate_s}%)", "file": "short_account.json",
                        "initial_capital": init_s, "cash": round(acct_short.get('cash', 0), 2),
                        "nav": round(nav_s, 2), "pnl_pct": round((nav_s / init_s - 1) * 100, 2),
                        "pnl_value": round(nav_s - init_s, 2),
                        "positions": pos_detail_s, "pos_count": len(pos_detail_s),
                    })

                # 3) 新引擎
                sim_path = BASE / 'sim_state.json'
                if sim_path.exists():
                    try:
                        from core.sim_engine import SimEngine
                        engine = SimEngine()
                        codes_n = [p['code'] for p in engine.acct.positions]
                        price_map_n = get_price_dict(codes_n)
                        pos_val_n = 0
                        pos_detail_n = []
                        for p in engine.acct.positions:
                            cp = price_map_n.get(p['code'])
                            cur = cp or p['avg_cost']
                            cost = p['avg_cost']
                            shares = p['shares']
                            mkt = cur * shares
                            pos_val_n += mkt
                            pnl = round((cur / cost - 1) * 100, 2) if cost else 0
                            pos_detail_n.append({
                                "code": p['code'], "name": p.get('name', ''),
                                "shares": shares, "cost": round(cost, 2),
                                "current": cur, "pnl_pct": pnl,
                                "pnl_value": round((cur - cost) * shares, 2),
                            })
                        nav_n = engine.acct.cash + pos_val_n
                        init_n = engine.acct.initial_capital
                        hit_n = sum(1 for p in pos_detail_n if p.get('pnl_pct', 0) > 0)
                        hit_rate_n = round(hit_n / max(len(pos_detail_n), 1) * 100, 1)
                        accounts.append({
                            "name": f"新引擎测试 ({hit_rate_n}%)", "file": "sim_state.json",
                            "initial_capital": init_n, "cash": round(engine.acct.cash, 2),
                            "nav": round(nav_n, 2), "pnl_pct": round((nav_n / init_n - 1) * 100, 2),
                            "pnl_value": round(nav_n - init_n, 2),
                            "positions": pos_detail_n, "pos_count": len(pos_detail_n),
                        })
                    except:
                        pass

                conn.close()
                self._json({"ok": True, "accounts": accounts, "date": datetime.now().strftime("%Y-%m-%d %H:%M")})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)})
            return

        elif path == '/api/sim_status':
            """模拟交易引擎状态"""
            try:
                from core.sim_engine import SimEngine
                engine = SimEngine()
                pos_detail = []
                for p in engine.acct.positions:
                    pnl = None
                    pos_detail.append({
                        "code": p['code'], "name": p.get('name', ''),
                        "shares": p['shares'], "cost": round(p['avg_cost'], 2),
                    })
                self._json({
                    "ok": True,
                    "initial_capital": engine.acct.initial_capital,
                    "cash": round(engine.acct.cash, 2),
                    "positions": pos_detail,
                    "pos_count": len(engine.acct.positions),
                    "nav_history": engine.acct.nav_history[-30:],
                    "trade_count": len(engine.acct.trades),
                    "config": {k: v for k, v in engine.config.items() if not isinstance(v, dict)},
                })
            except Exception as e:
                self._json({"ok": False, "msg": str(e)})

        elif path == '/api/sim_metrics':
            """模拟交易引擎绩效"""
            try:
                from core.sim_engine import SimEngine
                engine = SimEngine()
                metrics = engine.calc_metrics()
                self._json({"ok": True, "metrics": metrics})
            except Exception as e:
                self._json({"ok": False, "msg": str(e)})

        elif path == '/api/sim_run':
            """手动触发每日运行"""
            try:
                from core.sim_engine import SimEngine
                engine = SimEngine()
                result = engine.run_daily()
                metrics = engine.calc_metrics()
                self._json({
                    "ok": True,
                    "buys": len(result['buys']),
                    "sells": len(result['sells']),
                    "nav": result['nav'],
                    "buy_details": result['buys'],
                    "sell_details": result['sells'],
                    "risk": result['risk'],
                    "metrics": metrics,
                })
            except Exception as e:
                self._json({"ok": False, "msg": str(e)})

        elif path == '/api/candidates_today':
            # 返回活跃观察股（combined_score 信号）
            if HOLD_PATH.exists():
                data = json.loads(HOLD_PATH.read_text(encoding='utf-8'))
                active = [p for p in data.get('positions', [])
                         if p.get('status') in ('watch_active', 'watch_cold')]
                self._json({"date": datetime.now().strftime("%Y-%m-%d"), "candidates": active})
            else:
                self._json({"candidates": []})
        
        elif path == '/api/stock_detail':
            """个股详情数据（30秒缓存）"""
            code = params.get('code', [''])[0].strip()
            if not code:
                self._json({"ok": False, "msg": "缺少 code 参数"}, 400)
                return
            
            now = datetime.now().timestamp()
            cached = _api_cache.get(f'stock_detail_{code}')
            if cached and (now - cached['ts']) < 30:
                self._json(cached['data'])
                return
            
            # 从 DB 取日线数据
            daily_data, name = get_stock_daily_detail(code)
            
            # 从 holdings 取当前状态
            status_info = {"status": "unknown"}
            if HOLD_PATH.exists():
                holdings = json.loads(HOLD_PATH.read_text(encoding='utf-8'))
                for p in holdings.get('positions', []):
                    if p['code'] == code:
                        status_info = p
                        if not name:
                            name = p.get('name', '')
                        break
            
            # 账户持仓信息
            acct = load_account()
            acct_pos = None
            if acct:
                for p in acct.get('positions', []):
                    if p['code'] == code:
                        acct_pos = p
                        break
            
            analysis_result = analyze_stock(code, daily_data)
            data = {
                "ok": True,
                "code": code,
                "name": name,
                "status": status_info,
                "account_position": acct_pos,
                "daily": daily_data,
                "analysis_report": analysis_result.get('analysis', ''),
                "score": analysis_result.get('score'),
                "score_change": analysis_result.get('score_change'),
                "score_change_str": analysis_result.get('score_change_str', ''),
                "score_deltas": analysis_result.get('score_deltas', {}),
                "reg_pred": analysis_result.get('reg_pred'),
                "reg40_pred": analysis_result.get('reg40_pred'),
            }
            
            _api_cache[f'stock_detail_{code}'] = {'data': data, 'ts': now}
            self._json(data)
        
        elif path == '/detail':
            """个股详情页（独立页面）"""
            code = params.get('code', [''])[0].strip()
            if not code:
                self._html('<html><body style="background:#0f0f23;color:#e0e0e0;font:14px sans-serif;padding:40px;"><h2>缺少股票代码</h2><a href="/" style="color:#5af;">返回</a></body></html>')
                return
            
            # 获取数据
            daily_data, name = get_stock_daily_detail(code)
            analysis_result = analyze_stock(code, daily_data)
            acct = load_account()
            acct_pos = None
            if acct:
                for p in acct.get('positions', []):
                    if p['code'] == code:
                        acct_pos = p
                        break
            status_info = {"status": "unknown"}
            if HOLD_PATH.exists():
                holdings = json.loads(HOLD_PATH.read_text(encoding='utf-8'))
                for p in holdings.get('positions', []):
                    if p['code'] == code:
                        status_info = p
                        if not name:
                            name = p.get('name', '')
                        break
            
            # 构建详情页HTML
            score = analysis_result.get('score')
            reg_pred = analysis_result.get('reg_pred')
            reg40_pred = analysis_result.get('reg40_pred')
            analysis_text = analysis_result.get('analysis', '无数据')
            
            daily_json = json.dumps([{
                'd': r['date'] if isinstance(r, dict) else str(r[0]),
                'c': float(r['close']) if isinstance(r, dict) else float(r[1]),
            } for r in (daily_data or [])], ensure_ascii=False)
            
            acct_html = ''
            if acct_pos:
                cp = float(daily_data[-1]['close']) if daily_data and isinstance(daily_data[-1], dict) else float(daily_data[-1][1]) if daily_data else 0
                pnl = round((cp - acct_pos['avg_cost']) / acct_pos['avg_cost'] * 100, 2) if acct_pos['avg_cost'] > 0 else 0
                pnl_cls = 'green' if pnl >= 0 else 'red'
                acct_html = f'''
                <div class="section">
                <div class="section-title">📋 账户持仓</div>
                <table>
                <tr><th>持仓</th><th>成本</th><th>现价</th><th>盈亏%</th><th>市值</th></tr>
                <tr>
                <td>{acct_pos["shares"]}股</td>
                <td>{acct_pos["avg_cost"]:.2f}</td>
                <td>{cp:.2f}</td>
                <td class="{pnl_cls}">{"+" if pnl >= 0 else ""}{pnl}%</td>
                <td>{cp * acct_pos["shares"]:.0f}</td>
                </tr></table></div>'''
            
            score_html = ''
            if score is not None:
                sc = float(score)
                score_html += f'<span class="tag tag-{"hold" if sc >= 50 else "watch"}">评分 {sc:.0f}</span>'
            if reg_pred is not None:
                rp = float(reg_pred)
                score_html += f'<span class="tag" style="background:#{"00ff8822" if rp >= 0 else "ff446622"};color:{"#0f0" if rp >= 0 else "#f44"};">20日:{"+" if rp >= 0 else ""}{rp:.1f}%</span>'
            if reg40_pred is not None:
                rp40 = float(reg40_pred)
                score_html += f'<span class="tag" style="background:#{"00ff8822" if rp40 >= 0 else "ff446622"};color:{"#0f0" if rp40 >= 0 else "#f44"};">40日:{"+" if rp40 >= 0 else ""}{rp40:.1f}%</span>'
            
            # ── 每日跟踪表（近20日） ──
            track_rows = []
            # 加载历史评分
            score_hist = {}
            try:
                sh = json.load(open(BASE / 'score_history.json'))
                score_hist = sh
            except: pass
            if daily_data:
                for di in range(max(0, len(daily_data)-20), len(daily_data)):
                    dr = daily_data[di] if isinstance(daily_data[di], dict) else {'date':str(daily_data[di][0]),'close':float(daily_data[di][1]),'change_pct':float(daily_data[di][5]) if daily_data[di][5] else 0}
                    track_rows.append(dr)
                # 计算均线
                for i in range(len(track_rows)):
                    idx = len(daily_data) - len(track_rows) + i
                    cls70 = [float(d[1]) if not isinstance(d,dict) else d['close'] for d in daily_data[:idx+1]]
                    tr = track_rows[i]
                    c = tr['close']
                    ma5_t = sum(cls70[-5:])/5 if len(cls70)>=5 else c
                    ma20_t = sum(cls70[-20:])/20 if len(cls70)>=20 else c
                    ma60_t = sum(cls70[-60:])/60 if len(cls70)>=60 else c
                    tr['ma5'] = ma5_t; tr['ma20'] = ma20_t; tr['ma60'] = ma60_t
            track_html = ''
            if track_rows:
                track_html = '<div class="section"><div class="section-title">📋 近20日跟踪</div>'
                track_html += '<div style="overflow-x:auto;"><table style="font-size:11px;white-space:nowrap;">'
                track_html += '<thead><tr><th>日期</th><th>收盘</th><th>涨跌%</th><th>评分</th><th>MA5</th><th>MA20</th><th>MA60</th><th>均线</th></tr></thead><tbody>'
                for tr in reversed(track_rows):
                    chg_c = 'green' if tr.get('change_pct',0) >= 0 else 'red'
                    # 查历史评分
                    dt_key = tr['date'][:10]
                    sc_val = None
                    if score_hist and dt_key in score_hist:
                        day_sc = score_hist[dt_key]
                        if isinstance(day_sc, dict) and code in day_sc:
                            sv = day_sc[code]
                            if isinstance(sv, dict):
                                sc_val = sv.get('final_score', sv.get('fusion', None))
                            elif isinstance(sv, (int, float)):
                                sc_val = sv
                    if sc_val is None and track_rows and dt_key == track_rows[-1]['date'][:10] and score is not None:
                        sc_val = float(score)
                    sc_html = f'<td style="font-size:10px;color:#888;">{sc_val:.0f}</td>' if sc_val is not None else '<td style="font-size:10px;color:#555;">-</td>'
                    ma5_c = 'green' if tr['close'] > tr['ma5'] else 'red'
                    ma20_c = 'green' if tr['close'] > tr['ma20'] else 'red'
                    ma60_c = 'green' if tr['close'] > tr['ma60'] else 'red'
                    # 均线排列
                    ma_align = ''
                    if tr['close'] > tr['ma5'] > tr['ma20']:
                        ma_align = '✅多头'
                    elif tr['close'] < tr['ma5'] < tr['ma20']:
                        ma_align = '⚠️空头'
                    elif tr['close'] > tr['ma5']:
                        ma_align = '短期偏多'
                    else:
                        ma_align = '短期偏空'
                    track_html += f'<tr><td>{tr["date"][5:]}</td>'
                    track_html += f'<td>{tr["close"]:.2f}</td>'
                    track_html += f'<td class="{chg_c}">{tr.get("change_pct",0):+.1f}%</td>'
                    track_html += sc_html
                    track_html += f'<td class="{ma5_c}">{tr["ma5"]:.2f}</td>'
                    track_html += f'<td class="{ma20_c}">{tr["ma20"]:.2f}</td>'
                    track_html += f'<td class="{ma60_c}">{tr["ma60"]:.2f}</td>'
                    track_html += f'<td style="font-size:10px;">{ma_align}</td></tr>'
                track_html += '</tbody></table></div></div>'
            
            page = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name}({code}) - 个股详情</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font:14px -apple-system,'PingFang SC','Microsoft YaHei',monospace; background:#0f0f23; color:#e0e0e0; padding:20px; }}
h1 {{ color:#00d4ff; font-size:20px; margin-bottom:15px; }}
h2 {{ color:#00d4ff; font-size:15px; margin:15px 0 8px; }}
.section {{ background:#1a1a3e; border-radius:10px; padding:15px; margin-bottom:15px; }}
.section-title {{ font-size:12px; color:#888; margin-bottom:8px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ color:#666; font-weight:normal; font-size:11px; padding:6px 8px; text-align:left; border-bottom:1px solid #222; }}
td {{ padding:8px; border-bottom:1px solid #1a1a3e; }}
.tag {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; margin-right:6px; }}
.tag-hold {{ background:#00d4ff22; color:#00d4ff; }}
.tag-watch {{ background:#ffd70022; color:#ffd700; }}
.green {{ color:#00ff88; }}
.red {{ color:#ff4466; }}
.gray {{ color:#666; }}
pre {{ white-space:pre-wrap; font-size:13px; line-height:1.7; background:#0f0f23; padding:12px; border-radius:6px; margin:0; }}
#kline {{ width:100%; height:200px; background:#0f0f23; border-radius:6px; }}
.btn {{ display:inline-block; padding:6px 14px; border:1px solid #5af; border-radius:4px; background:#1a1a3e; color:#5af; text-decoration:none; font-size:13px; }}
.btn:hover {{ background:#2a2a5e; }}
</style></head>
<body>
<div style="display:flex;align-items:center;gap:12px;margin-bottom:15px;flex-wrap:wrap;">
<a href="/" class="btn">⬅ 返回</a>
<h1 style="margin:0;">{name or ""} ({code})</h1>
{score_html}
</div>

<div class="section">
<pre>{html.escape(analysis_text)}</pre>
</div>

{track_html}

<div class="section">
<div class="section-title">📈 120日走势</div>
<canvas id="kline" width="800" height="200"></canvas>
</div>

{acct_html}

<div class="section">
<div class="section-title">🔍 切换股票分析</div>
<div style="display:flex;gap:8px;">
<input id="d-code" value="{code}" size="12" style="padding:6px 10px;border:1px solid #333;border-radius:4px;background:#1a1a3e;color:#e0e0e0;font-size:13px;" onkeydown="if(event.key==='Enter')window.location.href='/detail?code='+document.getElementById('d-code').value.trim()">
<button class="btn" onclick="window.location.href='/detail?code='+document.getElementById('d-code').value.trim()">分析</button>
</div>
</div>

<script>
var daily = {daily_json};
function drawChart() {{
  var c = document.getElementById("kline");
  if (!c || daily.length === 0) return;
  var ctx = c.getContext("2d");
  var w = c.width, h = c.height, n = daily.length;
  var cls = daily.map(function(d){{return d.c;}});
  var mn = Math.min.apply(null, cls), mx = Math.max.apply(null, cls);
  var rng = mx - mn || 1;
  ctx.clearRect(0,0,w,h);
  ctx.strokeStyle = "#5af"; ctx.lineWidth = 1.5;
  ctx.beginPath();
  for(var i=0;i<n;i++){{
    var x = i/(n-1)*(w-20)+10;
    var y = h-10-(cls[i]-mn)/rng*(h-40);
    if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
  }}
  ctx.stroke();
  ctx.strokeStyle = "#222"; ctx.lineWidth = 0.5;
  for(var p=0;p<=100;p+=25){{var yg=h-10-p/100*(h-40); ctx.beginPath(); ctx.moveTo(10,yg); ctx.lineTo(w-10,yg); ctx.stroke();}}
  ctx.fillStyle = "#888"; ctx.font = "10px monospace";
  ctx.fillText(mn.toFixed(2), 4, h-6);
  ctx.fillText(mx.toFixed(2), 4, 12);
}}
drawChart();
</script>
</body></html>'''
            self._html(page)
        
        elif path == '/chat':
            """聊天页面"""
            chat_path = BASE / 'static' / 'chat.html'
            if chat_path.exists():
                self._html(chat_path.read_text(encoding='utf-8'))
            else:
                self._json({"error": "chat.html not found"}, 404)
        
        elif path == '/api/live_price':
            """批量获取实时价格（含DB fallback）"""
            codes_str = params.get('codes', [''])[0].strip()
            codes = [c.strip() for c in codes_str.split(',') if c.strip()]
            prices = fetch_prices_batch(codes)
            # fallback: DB for any missing
            for code in codes:
                if code not in prices or prices[code] is None:
                    _, cp = fetch_close_from_db(code)
                    if cp:
                        prices[code] = cp
            self._json({"ok": True, "prices": prices})
        
        elif path.startswith('/static/'):
            """静态文件（PWA manifest/图标）"""
            file_path = BASE / path.lstrip('/')
            if file_path.exists() and file_path.is_file():
                ext = file_path.suffix
                mime = {'json': 'application/json', 'png': 'image/png', 'ico': 'image/x-icon'}.get(ext.lstrip('.'), 'application/octet-stream')
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.end_headers()
                self.wfile.write(file_path.read_bytes())
            else:
                self._json({"error": "not found"}, 404)
        
        elif path == '/api/analyze':
            """手动分析单只股票"""
            code = params.get('code', [''])[0].strip()
            if not code:
                self._json({"ok": False, "msg": "缺少 code 参数"}, 400)
                return
            result = analyze_stock(code)
            result['ok'] = True
            self._json(result)
        
        else:
            self._json({"error": "not found"}, 404)
    
    def do_POST(self):
        if not self._require_auth():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == '/api/login':
            body = json.loads(self._read_body())
            pw = body.get('password', '')
            expected = hashlib.sha256(AUTH_PASSWORD.encode()).hexdigest()[:16]
            if pw == AUTH_PASSWORD:
                # 设置cookie，30天有效
                import http.cookies
                c = http.cookies.SimpleCookie()
                c['session_token'] = expected
                c['session_token']['path'] = '/'
                c['session_token']['max-age'] = 2592000  # 30天
                c['session_token']['httponly'] = True
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Set-Cookie', c['session_token'].OutputString())
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True}).encode('utf-8'))
            else:
                self._json({"ok": False, "msg": "密码错误"})
            return
        
        if path == '/api/sim_run':
            """POST触发模拟交易每日运行"""
            try:
                from core.sim_engine import SimEngine
                engine = SimEngine()
                result = engine.run_daily()
                metrics = engine.calc_metrics()
                self._json({
                    "ok": True,
                    "buys": len(result['buys']),
                    "sells": len(result['sells']),
                    "nav": result['nav'],
                    "risk": result['risk'],
                    "metrics": metrics,
                })
            except Exception as e:
                self._json({"ok": False, "msg": str(e)})
            return

        if path == '/api/trade':
            body = json.loads(self._read_body())
            action = body.get('action', '')
            code = body.get('code', '').strip()
            price = body.get('price')
            if not price:
                price, _ = fetch_price(code)
                price = price or 0
            else:
                price = float(price)
            
            acct = load_account()
            if not acct:
                self._json({"ok": False, "msg": "账户未初始化"})
                return
            
            if action == 'buy':
                name = body.get('name', '')
                if not name:
                    import os
                    try:
                        import duckdb
                        _db = duckdb.connect(os.path.join(str(BASE), 'stock.db'), read_only=True)
                        _r = _db.execute(f"SELECT stock_name FROM stock_info WHERE stock_code='{code}'").fetchone()
                        _db.close()
                        name = _r[0] if _r else code
                    except Exception as _e:
                        with open('/tmp/sim_buy_err.log','a') as _f: _f.write(f'{datetime.now()} {_e}\n')
                        name = code
                shares = body.get('shares')
                ok, msg = do_buy(acct, code, name, price, shares)
                if ok:
                    codes = [p['code'] for p in acct['positions']]
                    price_map = get_price_dict(codes)
                    update_nav(acct, price_map)
                    save_account(acct)
                    _append_alert('买入', code, name, price, shares, '手动操作')
                self._json({"ok": ok, "msg": msg})
            
            elif action == 'sell':
                shares = body.get('shares')
                # 卖之前先从持仓取名称
                sell_name = ''
                for p in acct['positions']:
                    if p['code'] == code:
                        sell_name = p.get('name', code)
                        break
                ok, msg = do_sell(acct, code, price, shares)
                if ok:
                    codes = [p['code'] for p in acct['positions']]
                    price_map = get_price_dict(codes)
                    update_nav(acct, price_map)
                    save_account(acct)
                    # 同步 holdings.json
                    try:
                        hdata = json.loads(HOLD_PATH.read_text(encoding='utf-8'))
                        for hp in hdata.get('positions', []):
                            if hp['code'] == code and hp.get('status') != 'archived':
                                hp['status'] = 'archived'
                                hp['archive_reason'] = '自动平仓'
                                hp['sell_price'] = price
                                break
                        with open(HOLD_PATH, 'w', encoding='utf-8') as f:
                            json.dump(hdata, f, ensure_ascii=False, indent=2)
                    except: pass
                    _append_alert('卖出', code, sell_name, price, shares, '手动操作', pnl=msg)
                self._json({"ok": ok, "msg": msg})
            
            else:
                self._json({"ok": False, "msg": f"未知操作: {action}"})
        
        else:
            self._json({"error": "not found"}, 404)
    
    def log_message(self, fmt, *args):
        pass  # 静默日志


# ── HTML 页面 ─────────────────────────────────────────

HTML_PAGE = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>模拟交易系统</title>
<link rel="manifest" href="/static/manifest.json">
<meta name="theme-color" content="#00d4ff">
<meta name="apple-mobile-web-app-capable" content="yes">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font: 14px -apple-system, 'PingFang SC', 'Microsoft YaHei', monospace; background: #0f0f23; color: #e0e0e0; padding: 20px; }
h1 { color: #00d4ff; font-size: 22px; margin-bottom: 20px; }
h2 { color: #00d4ff; font-size: 16px; margin: 25px 0 10px; display: flex; align-items: center; gap: 10px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 20px; }
.card { background: #1a1a3e; padding: 15px; border-radius: 10px; text-align: center; }
.card .label { font-size: 11px; color: #888; margin-bottom: 6px; }
.card .num { font-size: 24px; font-weight: bold; font-variant-numeric: tabular-nums; }
.cash { color: #00d4ff; }
.green { color: #00ff88; }
.red { color: #ff4466; }
.yellow { color: #ffd700; }
.gray { color: #666; }
table { width: 100%; border-collapse: collapse; margin-bottom: 15px; font-size: 13px; }
th { color: #666; font-weight: normal; font-size: 11px; padding: 6px 8px; text-align: left; border-bottom: 1px solid #222; white-space: nowrap; }
td { padding: 8px; border-bottom: 1px solid #1a1a3e; white-space: nowrap; }
tr:hover { background: #1a1a3e55; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
.tag-hold { background: #00d4ff22; color: #00d4ff; }
.tag-watch { background: #ffd70022; color: #ffd700; }
.tag-sold { background: #446; color: #888; }
.btn { padding: 5px 14px; border: 1px solid #444; border-radius: 4px; background: #1a1a3e; color: #e0e0e0; cursor: pointer; font-size: 12px; }
.btn:hover { background: #2a2a5e; }
.btn-buy { border-color: #00ff88; color: #00ff88; }
.btn-sell { border-color: #ff4466; color: #ff4466; }
.btn-refresh { border-color: #00d4ff; color: #00d4ff; }
.btn-sm { padding: 3px 10px; font-size: 11px; }
.form-row { display: flex; gap: 8px; margin: 10px 0; align-items: center; flex-wrap: wrap; }
.form-row input, .form-row select { padding: 6px 10px; border: 1px solid #333; border-radius: 4px; background: #1a1a3e; color: #e0e0e0; font-size: 13px; }
#chart-container { background: #1a1a3e; border-radius: 10px; padding: 15px; margin-bottom: 20px; }
#navChart { width: 100%; height: 240px; }
#result { margin-top: 10px; padding: 8px 12px; border-radius: 4px; }
#result.ok { background: #00ff8811; color: #00ff88; }
#result.err { background: #ff446611; color: #ff4466; }
.flex { display: flex; gap: 15px; align-items: center; flex-wrap: wrap; }
.ml-auto { margin-left: auto; }
.text-right { text-align: right; }
@media (max-width: 600px) {
  body { padding: 10px; }
  table { font-size: 11px; }
  th, td { padding: 4px 6px; }
  .cards { grid-template-columns: repeat(2, 1fr); }
}
/* Scrollable table container */
.table-wrap { overflow-x: auto; }
</style>
</head>
<body>

<h1>📊 模拟交易系统</h1>

<div id="main-content">
<div class="cards" id="cards"></div>

<h2>📊 三系统汇总</h2>
<div class="cards" id="all-acct-cards"></div>

<div id="all-acct-pos" style="margin-bottom:20px;"></div>

<h2>📋 持仓明细</h2>
<div id="chart-container">
  <canvas id="navChart"></canvas>
</div>

<h2>📌 持仓 
  <span class="tag tag-hold" id="pos-count">0</span>
  <button class="btn btn-refresh btn-sm ml-auto" onclick="updateNav()">更新净值</button>
  <button class="btn btn-refresh btn-sm" onclick="loadStatus()">刷新</button>
</h2>
<div class="table-wrap"><table><thead><tr>
  <th>代码</th><th>名称</th><th>现价</th><th>成本</th><th>盈亏%</th><th>市值</th><th>持股</th><th>v5评分</th><th>目标价</th><th>预测涨幅</th>
</tr></thead><tbody id="pos-body"></tbody></table></div>

<h2>👁️ 观察名单
  <button class="btn btn-buy btn-sm ml-auto" onclick="loadWatch()">刷新</button>
</h2>
<div class="table-wrap"><table><thead><tr>
  <th>代码</th><th>名称</th><th>现价</th><th>介入区间</th><th>止损</th><th>目标</th><th>v5评分</th><th>状态</th>
</tr></thead><tbody id="watch-body"></tbody></table></div>

<h2>📡 手动分析
  <button class="btn btn-refresh btn-sm" onclick="analyzeStock()">分析</button>
</h2>
<div class="form-row">
  <input id="analyze-code" placeholder="输入6位股票代码" size="12" onkeydown="if(event.key==='Enter')analyzeStock()">
  <button class="btn btn-refresh btn-sm" onclick="analyzeStock()">分析</button>
</div>
<div id="analyze-result" style="margin-top:10px;"></div>

<h2>💼 手动操作</h2>
<div class="form-row">
  <select id="action">
    <option value="buy">买入</option>
    <option value="sell">卖出</option>
  </select>
  <input id="code" placeholder="6位代码" size="8">
  <input id="price" placeholder="价格(留空自动)" size="10">
  <input id="shares" placeholder="股数" size="6">
  <button class="btn" onclick="doTrade()">执行</button>
</div>
<div id="result"></div>

<h2>📋 交易流水</h2>
<div class="table-wrap"><table><thead><tr>
  <th>日期</th><th>方向</th><th>名称</th><th>代码</th><th>价格</th><th>数量</th><th>金额</th><th>盈亏</th>
</tr></thead><tbody id="trade-body"></tbody></table></div>

<h2>🤖 自动信号</h2>
<div id="signal-log" style="background:#1a1a3e; border-radius:6px; padding:8px; font-size:11px; line-height:1.6; max-height:180px; overflow-y:auto;">
  <span style="color:#666">加载中...</span>
</div>

</div><!-- /main-content -->

<script>
let statusData = null;

async function getJson(url) {
  const r = await fetch(url);
  return await r.json();
}

async function postJson(url, data) {
  const r = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(data)
  });
  return await r.json();
}

// ── 概览卡片 ──
async function loadStatus() {
  try {
    const data = await getJson("/api/status");
    if (!data.ok) {
      document.getElementById("cards").innerHTML = "<div class=\"card\"><div class=\"label\">状态</div><div>" + data.msg + "</div></div>";
      return;
    }
    statusData = data;
    var pnlCls = data.total_pnl_pct >= 0 ? "green" : "red";
    document.getElementById("cards").innerHTML = 
      "<div class=\"card\"><div class=\"label\">总资产</div><div class=\"num cash\">" + data.nav.toLocaleString() + "</div></div>" +
      "<div class=\"card\"><div class=\"label\">总盈亏</div><div class=\"num " + pnlCls + "\">" + (data.total_pnl_pct >= 0 ? "+" : "") + data.total_pnl_pct + "%</div></div>" +
      "<div class=\"card\"><div class=\"label\">现金</div><div class=\"num cash\">" + data.cash.toLocaleString() + "</div></div>" +
      "<div class=\"card\"><div class=\"label\">持仓市值</div><div class=\"num\">" + data.position_value.toLocaleString() + "</div></div>" +
      "<div class=\"card\"><div class=\"label\">持仓数量</div><div class=\"num\">" + data.position_count + "</div></div>" +
      "<div class=\"card\"><div class=\"label\">持仓命中</div><div class=\"num yellow\">" + data.hold_hit_rate + "%</div></div>" +
      "<div class=\"card\"><div class=\"label\">胜率</div><div class=\"num yellow\">" + data.win_rate + "%</div></div>";
    document.getElementById("pos-count").textContent = data.position_count;
    
    var body = document.getElementById("pos-body");
    if (!data.positions || data.positions.length === 0) {
      body.innerHTML = "<tr><td colspan=\"11\" class=\"gray\" style=\"text-align:center;padding:20px;\">暂无持仓</td></tr>";
      return;
    }
    body.innerHTML = data.positions.map(function(p) {
      var pnlCls2 = p.pnl_pct >= 0 ? "green" : "red";
      return "<tr>" +
        "<td><a href=\"/detail?code=" + p.code + "\" style=\"color:#5af;\">" + p.code + "</a></td>" +
        "<td>" + (p.name || "") + "</td>" +
        "<td>" + p.current_price.toFixed(2) + "</td>" +
        "<td>" + p.avg_cost.toFixed(2) + "</td>" +
        "<td class=\"" + pnlCls2 + "\">" + (p.pnl_pct >= 0 ? "+" : "") + p.pnl_pct.toFixed(1) + "%</td>" +
        "<td>" + (p.market_value || 0).toLocaleString() + "</td>" +
        "<td>" + (p.shares || 0) + "</td>" +
        "<td>" + (p.v5_score || "-") + "</td>" +
        "<td>" + (p.target ? p.target.toFixed(2) : "-") + "</td>" +
        "<td>" + (p.reg_pred != null ? (p.reg_pred >= 0 ? "+" : "") + p.reg_pred + "%" : "-") + "</td>" +
        "</tr>";
    }).join("");
  } catch (e) {
    document.getElementById("cards").innerHTML = "<div style=\"color:#ff4466\">加载失败: " + e.message + "</div>";
  }
}

// ── 三系统汇总 ──
async function loadAllAccounts() {
  try {
    const data = await getJson("/api/all_accounts");
    if (!data.ok) { return; }
    const accts = data.accounts || [];
    
    // 概要卡片
    const cardsHtml = accts.map(function(a) {
      var cls = a.pnl_pct >= 0 ? "green" : "red";
      return "<div class=\"card\" style=\"border:1px solid #333;\">" +
        "<div class=\"label\">" + a.name + "</div>" +
        "<div class=\"num " + cls + "\">" + (a.pnl_pct >= 0 ? "+" : "") + a.pnl_pct + "%</div>" +
        "<div style=\"font-size:11px;color:#888;margin-top:4px;\">" + a.nav.toLocaleString() + " / " + a.pos_count + "只</div>" +
        "</div>";
    }).join("");
    document.getElementById("all-acct-cards").innerHTML = cardsHtml + 
      "<div class=\"card\" style=\"border:1px solid #333;\"><div class=\"label\">合计</div><div class=\"num cash\">" +
      accts.reduce(function(s,a){return s+a.nav;},0).toLocaleString() + "</div>" +
      "<div style=\"font-size:11px;color:#888;margin-top:4px;\">" + accts.reduce(function(s,a){return s+a.initial_capital;},0).toLocaleString() + "</div></div>";

    // 持仓明细
    var posHtml = "";
    accts.forEach(function(a) {
      if (!a.positions || a.positions.length === 0) return;
      posHtml += "<h3 style=\"font-size:13px;margin:8px 0 4px;color:#5af;\">" + a.name + "</h3>";
      posHtml += "<div class=\"table-wrap\"><table style=\"font-size:12px;\"><thead><tr>" +
        "<th>代码</th><th>名称</th><th>股数</th><th>成本</th><th>现价</th><th>盈亏%</th><th>盈亏额</th></tr></thead><tbody>";
      a.positions.forEach(function(p) {
        var cls2 = p.pnl_pct >= 0 ? "green" : "red";
        posHtml += "<tr><td><a href=\"/detail?code=" + p.code + "\" style=\"color:#5af;\">" + p.code + "</a></td><td>" + p.name + "</td><td>" + p.shares + "</td>" +
          "<td>" + p.cost.toFixed(2) + "</td><td>" + p.current.toFixed(2) + "</td>" +
          "<td class=\"" + cls2 + "\">" + (p.pnl_pct >= 0 ? "+" : "") + p.pnl_pct.toFixed(2) + "%</td>" +
          "<td class=\"" + cls2 + "\">" + (p.pnl_value >= 0 ? "+" : "") + p.pnl_value.toFixed(0) + "</td></tr>";
      });
      posHtml += "</tbody></table></div>";
    });
    document.getElementById("all-acct-pos").innerHTML = posHtml;
  } catch(e) {}
}

// ── 观察表 ──
async function loadWatch() {
  try {
    var results = await Promise.all([getJson("/api/holdings"), getJson("/api/price_alerts")]);
    var data = results[0];
    var alerts = results[1];
    var watchList = (data.positions || []).filter(function(p) { return p.status === "watch" || p.status === "watch_active" || p.status === "watch_cold"; });
    var body = document.getElementById("watch-body");
    if (watchList.length === 0) {
      body.innerHTML = "<tr><td colspan=\"8\" class=\"gray\" style=\"text-align:center;padding:20px;\">暂无观察</td></tr>";
      return;
    }
    var codes = watchList.map(function(p) { return p.code; });
    var priceMap = {};
    try {
      var r = await getJson("/api/live_price?codes=" + codes.join(","));
      if (r && r.prices) Object.assign(priceMap, r.prices);
    } catch(e) {}
    
    body.innerHTML = watchList.map(function(p) {
      var tagMap = {hold:"hold", watch:"watch", watch_active:"watch", watch_cold:"watch"};
      var labelMap = {hold:"持仓", watch:"观察", watch_active:"活跃关注", watch_cold:"等回调"};
      var tagCls = tagMap[p.status] || "watch";
      var label = labelMap[p.status] || "观察";
      var entry = (p.entry_low && p.entry_high) ? p.entry_low + "~" + p.entry_high : "-";
      var price = priceMap[p.code];
      var alert = alerts[p.code];
      var inRange = alert && alert.triggered;
      return "<tr>" +
        "<td><a href=\"/detail?code=" + p.code + "\" style=\"color:#5af;\">" + p.code + "</a></td>" +
        "<td>" + (p.name || "") + " <span class=\"tag tag-" + tagCls + "\">" + label + "</span></td>" +
        "<td>" + (price ? price.toFixed(2) : "-") + "</td>" +
        "<td>" + entry + "</td>" +
        "<td>" + (p.stop_loss || "-") + "</td>" +
        "<td>" + (p.target || "-") + "</td>" +
        "<td>" + (p.v5_score || "-") + "</td>" +
        "<td>" + (inRange ? "<span style=\"color:#0f0;\">到价</span>" : "") + "</td>" +
        "</tr>";
    }).join("");
  } catch(e) {
    console.error(e);
  }
}

// ── 交易流水 ──
async function loadTrades() {
  try {
    var data = await getJson("/api/trade_log");
    if (!data || !data.trades) return;
    var body = document.getElementById("trade-body");
    var reversed = data.trades.slice().reverse();
    if (reversed.length === 0) {
      body.innerHTML = "<tr><td colspan=\"8\" class=\"gray\" style=\"text-align:center;padding:20px;\">暂无交易记录</td></tr>";
      return;
    }
    body.innerHTML = reversed.map(function(t) {
      var actionCls = t.action === "买入" ? "green" : "red";
      var pnl = t.pnl != null ? (t.pnl >= 0 ? "+" : "") + t.pnl + "%" : "-";
      var pnlCls = t.pnl >= 0 ? "green" : "red";
      return "<tr>" +
        "<td>" + (t.date || "") + "</td>" +
        "<td class=\"" + actionCls + "\">" + (t.action || "") + "</td>" +
        "<td>" + (t.name || "") + "</td>" +
        "<td>" + (t.code || "") + "</td>" +
        "<td>" + (t.price || "") + "</td>" +
        "<td>" + (t.shares || "") + "</td>" +
        "<td>" + (t.amount || "") + "</td>" +
        "<td class=\"" + pnlCls + "\">" + pnl + "</td>" +
        "</tr>";
    }).join("");
  } catch(e) {}
}

// ── 操作 ──
async function doTrade() {
  var action = document.getElementById("action").value;
  var code = document.getElementById("code").value.trim();
  var price = document.getElementById("price").value.trim();
  var shares = document.getElementById("shares").value.trim();
  if (!code) { alert("请输入代码"); return; }
  var body = {action: action, code: code};
  if (price) body.price = parseFloat(price);
  if (shares) body.shares = parseInt(shares);
  try {
    var r = await postJson("/api/trade", body);
    document.getElementById("result").innerHTML = r.ok ? "<span style=\"color:#0f0\">OK: " + r.msg + "</span>" : "<span style=\"color:#f44\">FAIL: " + r.msg + "</span>";
    setTimeout(loadStatus, 500);
    setTimeout(loadTrades, 500);
  } catch(e) {
    document.getElementById("result").innerHTML = "<span style=\"color:#f44\">ERROR: " + e.message + "</span>";
  }
}

// ── 手动分析 ──
function escapeHtml(t) {
  if (!t) return '';
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

async function analyzeStock() {
  var code = document.getElementById("analyze-code").value.trim();
  if (!code) {
    document.getElementById("analyze-result").innerHTML = "<div style=\"color:#ff4466;padding:10px;\">请输入6位股票代码</div>";
    return;
  }
  var el = document.getElementById("analyze-result");
  el.innerHTML = "<div style=\"color:#888;\">加载中...</div>";
  try {
    var r = await getJson("/api/analyze?code=" + code);
    // 评分条
    var scoreHtml = '';
    if (r.score != null) {
      var sc = parseFloat(r.score);
      scoreHtml += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;">';
      scoreHtml += '<span class="tag ' + (sc >= 50 ? 'tag-hold' : 'tag-watch') + '">评分 ' + sc.toFixed(0) + '</span>';
      if (r.reg_pred != null) {
        var rp = parseFloat(r.reg_pred);
        scoreHtml += '<span style="font-size:12px;background:#' + (rp >= 0 ? '00ff8822' : 'ff446622') + ';color:' + (rp >= 0 ? '#0f0' : '#f44') + ';padding:2px 8px;border-radius:4px;">20日预测: ' + (rp >= 0 ? "+" : "") + rp.toFixed(1) + '%</span>';
      }
      if (r.score_detail) {
        var sd = r.score_detail;
        scoreHtml += '<span style="font-size:11px;color:#888;">多头' + (sd['多头信号'] || '?') + '/' + (sd['空头信号'] || '?') + '</span>';
      }
      scoreHtml += '</div>';
    }
    el.innerHTML = scoreHtml + '<pre style="white-space:pre-wrap;font-size:13px;line-height:1.6;background:#111;padding:10px;border-radius:6px;">' + escapeHtml(r.analysis) + '</pre>';
    el.scrollIntoView({behavior: "smooth", block: "start"});
  } catch(e) {
    el.innerHTML = "<div style=\"color:#ff4466\">分析失败: " + e.message + "</div>";
  }
}

// ── 简版K线 ──
function drawChart(daily) {
  var canvas = document.getElementById("navChart");
  if (!canvas || !daily || daily.length === 0) return;
  var ctx = canvas.getContext("2d");
  var w = canvas.width, h = canvas.height, n = daily.length;
  var closes = daily.map(function(d) { return d.close; });
  var mn = Math.min.apply(null, closes), mx = Math.max.apply(null, closes);
  var rng = mx - mn || 1;
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = "#5af"; ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (var i = 0; i < n; i++) {
    var x = i / (n-1) * (w-20) + 10;
    var y = h - 10 - (closes[i] - mn) / rng * (h-40);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

loadStatus();
loadAllAccounts();
loadWatch();
loadTrades();
</script>
</body>
</html>"""

# ── 启动 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='模拟交易系统')
    parser.add_argument('--port', type=int, default=8080, help='监听端口')
    args = parser.parse_args()
    global PORT
    PORT = args.port

    # 清除代理，防止 urllib 走梯子导致请求挂死
    for k in ['http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
        os.environ.pop(k, None)

    # 首次启动自动同步
    if not ACCT_PATH.exists():
        print("📦 首次启动，从 holdings.json 同步持仓...")
        sync_from_holdings()
    
    # 启动实时价格监控
    t = threading.Thread(target=_price_monitor_thread, daemon=True)
    t.start()
    print("   📡 实时价格监控已启动（15秒/次）")

    server = ThreadingHTTPServer(('0.0.0.0', PORT), SimHandler)
    print(f"🌐 模拟交易系统 http://localhost:{PORT}")
    print(f"   PID: {os.getpid()}")
    print(f"   账户: {ACCT_PATH}")
    print("   Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 已停止")
        server.server_close()

if __name__ == '__main__':
    main()
