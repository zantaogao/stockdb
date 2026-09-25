"""
统一价格获取（Sina API，快且可靠，不用 DB 收盘价兜底）
"""
import urllib.request
from datetime import datetime
from core.db import get_db

_price_cache = {}
_PRICE_CACHE_TTL = 15  # 15秒缓存，盘中频繁调用也不用重复请求

INDEX_SINA = {'000001': 'sh000001', '399001': 'sz399001', '399006': 'sz399006',
              '000852': 'sh000852'}  # 2026-08-05: 加中证1000（策略账户市场基准）


def sina_code(code):
    return f"sh{code}" if code.startswith(('6', '68', '9')) else f"sz{code}"


def _fetch_sina(codes):
    """新浪行情（全天候）"""
    try:
        sina_codes = ','.join(INDEX_SINA.get(c) or sina_code(c) for c in codes)
        req = urllib.request.Request(f"https://hq.sinajs.cn/list={sina_codes}",
                                     headers={"Referer": "https://finance.sina.com.cn"})
        raw = urllib.request.urlopen(req, timeout=3).read().decode('gbk')
        result = {}
        for line in raw.strip().split('\n'):
            if '=""' in line or 'hq_str_' not in line:
                continue
            scode = line.split('hq_str_')[1].split('=')[0]
            parts = line.split('"')[1].split(',')
            c = scode[2:] if scode.startswith(('sh', 'sz')) else scode
            open_p = float(parts[1]) if len(parts) > 1 and parts[1] else None   # 今开 (2026-08-08 低吸信号用)
            price = float(parts[3]) if len(parts) > 3 and parts[3] else None
            prev = float(parts[2]) if len(parts) > 2 and parts[2] else None
            if price and c in codes:
                result[c] = {'price': price, 'prev': prev, 'open': open_p}
        return result
    except:
        return {}


def fetch_prices_batch(codes):
    """
    批量获取实时价格：仅 Sina API（快且可靠），不用 TDX 避免长时间挂起
    失败返回空字典
    """
    now_ts = datetime.now().timestamp()
    result = {}
    need = []
    for code in codes:
        cached = _price_cache.get(code)
        if cached and (now_ts - cached['ts']) < _PRICE_CACHE_TTL:
            result[code] = cached['price']
        else:
            need.append(code)
    if not need:
        return result

    data = _fetch_sina(need)
    for code in need:
        if code in data:
            p = data[code]['price']
            pv = data[code].get('prev')
            po = data[code].get('open')
            result[code] = p
            _price_cache[code] = {'price': p, 'prev': pv, 'open': po, 'ts': now_ts}
        else:
            _price_cache.pop(code, None)

    return result


def fetch_price_open(code):
    """获取当日开盘价（2026-08-08 低吸信号用: 现价>开盘价=开盘走强确认）"""
    now_ts = datetime.now().timestamp()
    cached = _price_cache.get(code)
    if cached and (now_ts - cached['ts']) < _PRICE_CACHE_TTL:
        return cached.get('open')
    data = _fetch_sina([code])
    if code in data:
        return data[code].get('open')
    return None


def fetch_price_prev(code):
    """获取昨收价（2026-08-08 高开 gap 计算用）"""
    now_ts = datetime.now().timestamp()
    cached = _price_cache.get(code)
    if cached and (now_ts - cached['ts']) < _PRICE_CACHE_TTL:
        return cached.get('prev')
    data = _fetch_sina([code])
    if code in data:
        return data[code].get('prev')
    return None


def fetch_price_live(code):
    """单只股票实时价，返回 (价格, 涨跌幅%)"""
    prices = fetch_prices_batch([code])
    if code in prices:
        cached = _price_cache.get(code, {})
        prev = cached.get('prev')
        price = prices[code]
        chg_pct = ((price / prev) - 1) * 100 if prev and prev > 0 else 0
        return price, chg_pct
    return None, 0


def fetch_close_from_db(code):
    """从 daily (tushare) 获取最新收盘价（兜底）"""
    try:
        db = get_db(read_only=True)
        try:
            ts_code = f"{code}.SH" if code.startswith(('6', '68', '9')) else f"{code}.SZ"
            r = db.execute(f"SELECT trade_date, close FROM daily WHERE ts_code='{ts_code}' ORDER BY trade_date DESC LIMIT 1").fetchone()
            if r:
                return str(r[0]), float(r[1])
        finally:
            db.close()
        return None, None
    except:
        return None, None


def get_price(code):
    """实时价→DB兜底"""
    price, prev = fetch_price_live(code)
    if price:
        return price, prev
    _, close = fetch_close_from_db(code)
    return close, close


def get_price_dict(codes):
    return fetch_prices_batch(codes)
