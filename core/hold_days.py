"""持有天数计算（交易日口径，2026-08-07 建立）
intraday_decision.py（盘中决策卖出规则 R2 达目标价持5天 / R5 持20天）
与 server_dashboard.py（面板显示）共用单一实现，避免口径漂移。

口径：COUNT(DISTINCT trade_date) FROM daily WHERE trade_date BETWEEN 买入日 AND 今天
——daily 每天 16:00 更新，全市场交易日历一致（停牌股不影响）。
买入当日算第 1 天；今日买入（daily 无今日行）返回 0（T+1 也挡当天卖出）。

缓存：daily 一天只更新一次，交易日历按"今天"缓存，跨天自动失效。
面板 35 只持仓 × 每次 API 请求免重复查 DuckDB（首次 1-2 秒，之后内存计数）。
"""
import duckdb
from datetime import datetime

from core.db import TUSHARE_DB_PATH

_trade_dates_cache = {'as_of': None, 'dates': None}


def _get_trade_dates():
    """取截止今天的所有交易日（YYYYMMDD 字符串升序），缓存到日期变化"""
    today = datetime.now().strftime('%Y%m%d')
    if _trade_dates_cache['as_of'] != today:
        conn = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)
        try:
            dates = [r[0] for r in conn.execute(
                "SELECT DISTINCT trade_date FROM daily WHERE trade_date <= ? ORDER BY trade_date",
                (today,)).fetchall()]
        finally:
            conn.close()
        _trade_dates_cache['as_of'] = today
        _trade_dates_cache['dates'] = dates
    return _trade_dates_cache['dates']


def calc_holding_days(buy_date_str) -> int:
    """按交易日计算持仓天数，兼容 YYYY-MM-DD / YYYYMMDD 输入，异常/空返回 0"""
    if not buy_date_str:
        return 0
    try:
        bd = str(buy_date_str).strip()
        if '-' in bd:
            buy = datetime.strptime(bd[:10], '%Y-%m-%d').date()
            buy_yyyymmdd = buy.strftime('%Y%m%d')
        else:
            buy_yyyymmdd = bd[:8]
        today_yyyymmdd = datetime.now().strftime('%Y%m%d')
        if buy_yyyymmdd > today_yyyymmdd:
            return 0
        dates = _get_trade_dates()
        return sum(1 for d in dates if buy_yyyymmdd <= d <= today_yyyymmdd)
    except Exception:
        return 0
