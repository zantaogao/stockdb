# 交易日历 helper（供 check_and_alert.sh 等 python3 -c 嵌入块 import）
# 权威源: stockdb/data/trade_cal.json（gen_trade_cal.py 从 tushare trade_cal 生成，
# 独立于被检查的库——2026-09-26 设计，09-25 调休休市误报复盘后接入本脚本）。
# 日历缺日/未覆盖 → 回退"只跳周末"近似（与 health_check_scores.py 同策略）。
import json, datetime
from pathlib import Path

_CAL_FILE = Path('/Users/zantao/.hermes/stockdb/data/trade_cal.json')

def _load():
    try:
        d = json.load(open(_CAL_FILE))
        s = set(d.get('is_open_dates') or [])
        if s:
            return s, tuple(d.get('range') or (None, None))
    except Exception:
        pass
    return None, (None, None)

OPEN_DATES, CAL_RANGE = _load()

def recent_trading_day(d):
    """d(date 或 YYYYMMDD str) 当天或之前最近交易日，返回 date。"""
    if isinstance(d, str):
        d = datetime.datetime.strptime(d.replace('-', '')[:8], '%Y%m%d').date()
    if OPEN_DATES:
        ds = d.strftime('%Y%m%d')
        steps = 0
        while ds not in OPEN_DATES and steps < 60:
            d -= datetime.timedelta(days=1)
            ds = d.strftime('%Y%m%d')
            steps += 1
        if ds in OPEN_DATES:
            return d
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d

def is_open(d):
    """d(YYYYMMDD str) 是否交易日；日历未覆盖时回退"非周末即交易日"。"""
    ds = str(d).replace('-', '')[:8]
    if OPEN_DATES:
        lo, hi = CAL_RANGE
        if lo and hi and lo <= ds <= hi:
            return ds in OPEN_DATES
    dt = datetime.datetime.strptime(ds, '%Y%m%d').date()
    return dt.weekday() < 5
