# -*- coding: utf-8 -*-
"""rqalpha 数据 mod —— 我方分钟线库直供（stockdb 治理 Task 3.2 骨架 v0）。

设计（与 2.2 锁定口径一致）：
- 日线：tushare.db stock_daily 只读 → numpy 结构化数组（bdist 字段序）按日缓存
- 分钟线：minutes/5min/*.parquet 直读；bar 标签 = bar-结束口径（2.2 断言锁定），直读不转换
- 停牌：缺 bar 反推（某票某交易日无 bar=停牌；主源=我方 5254 票自库，不依赖限流外部源；suspend_d 交叉验证后置）
- 复权：v0 只提供 pre 乘数（tushare adj_factor 最新日归一）；RQAlpha 若二次复权则配 pre 会双复权——对拍时经
  history_bars(adjust_type='none') 路径统一，口径写入本文件头（Task 3.2 验收项）

⚠ 本类为 v0 遗留路径（独立 AbstractDataSource 实现）。Task 3.2 定案走
**bundle + BaseDataSource**（build_bundle.py 生成 rqalpha_lab/bundle/，exp_config.yml 配
data_bundle_path 直接用原生 BaseDataSource，不加载本 mod 的数据源）。本文件保留为
"分钟线直供 mod"备选（免 bundle、分钟线直读 parquet），v0 未跑通（历史 401/403 即此路径）。
"""
import os
import datetime as _dt
from functools import lru_cache
from typing import Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

from rqalpha.const import INSTRUMENT_TYPE, MARKET, TRADING_CALENDAR_TYPE
from rqalpha.data.base_data_source import BaseDataSource
from rqalpha.data.base_data_source.storage_interface import (
    AbstractCalendarStore, AbstractDateSet, AbstractDayBarStore)
from rqalpha.interface import AbstractMod, AbstractPriceBoard
from rqalpha.model.instrument import Instrument

HOME = os.path.expanduser("~")
STOCKDB = os.path.join(HOME, ".hermes", "stockdb")
DB5 = os.path.join(STOCKDB, "minutes", "5min")
TUSHARE = os.path.join(STOCKDB, "tushare.db")
TRADE_CAL = os.path.join(STOCKDB, "minutes", "trade_cal_5min.json")

DAY_DTYPE = np.dtype([
    ("datetime", "<u8"), ("trading_date", "<u4"),
    ("open", "<f8"), ("high", "<f8"), ("low", "<f8"), ("close", "<f8"),
    ("limit_up", "<f8"), ("limit_down", "<f8"),
    ("volume", "<f8"), ("total_turnover", "<f8"),
])


def _to_obid(ts_code: str) -> str:
    """600000.SH -> 600000.XSHG（RQAlpha 惯例）"""
    code, ex = ts_code.split(".")
    return code + (".XSHG" if ex == "SH" else ".XSHE")


def _from_obid(order_book_id: str) -> str:
    code, ex = order_book_id.split(".")
    return code + (".SH" if ex == "XSHG" else ".SZ")


def _dt_int(d) -> int:
    if isinstance(d, (int, np.integer)):
        return int(d)
    if isinstance(d, (_dt.date, _dt.datetime)):
        return d.year * 10000 + d.month * 100 + d.day
    return int(pd.Timestamp(str(d)).strftime("%Y%m%d"))


class StockdbDayStore(AbstractDayBarStore):
    """tushare stock_daily → 结构化数组，按票缓存（LRU 上限防爆内存）。"""

    def __init__(self):
        self._cache = {}

    def _load(self, order_book_id: str) -> Optional[np.ndarray]:
        if order_book_id in self._cache:
            return self._cache[order_book_id]
        import duckdb
        ts = _from_obid(order_book_id)
        try:
            con = duckdb.connect(TUSHARE, read_only=True)
            df = con.execute(
                "select trade_date, open, high, low, close, vol, amount "
                "from stock_daily where ts_code=? order by trade_date", [ts]).df()
            con.close()
        except Exception:
            self._cache[order_book_id] = None
            return None
        if df is None or df.empty:
            self._cache[order_book_id] = None
            return None
        arr = np.empty(len(df), dtype=DAY_DTYPE)
        dates = pd.to_datetime(df["trade_date"].astype(str))
        arr["datetime"] = dates.values.astype("datetime64[s]").astype("<u8") * 1000
        arr["trading_date"] = dates.dt.strftime("%Y%m%d").astype(int).values
        for i, col in enumerate(["open", "high", "low", "close"]):
            arr[3 + i] = df[col].astype(float).values
        arr["volume"] = df["vol"].astype(float).values * 100.0      # tushare 手→股
        arr["total_turnover"] = df["amount"].astype(float).values * 1000.0  # 千元→元
        arr["limit_up"] = np.nan
        arr["limit_down"] = np.nan
        self._cache[order_book_id] = arr
        return arr

    def get_bars(self, order_book_id):
        return self._load(order_book_id)

    def get_date_range(self, order_book_id):
        a = self._load(order_book_id)
        if a is None or len(a) == 0:
            return None
        first = _dt.datetime.strptime(str(int(a["trading_date"][0])), "%Y%m%d").date()
        last = _dt.datetime.strptime(str(int(a["trading_date"][-1])), "%Y%m%d").date()
        return first, last


class StockdbCalendarStore(AbstractCalendarStore):
    def get_trading_calendar(self):
        import json
        days = json.load(open(TRADE_CAL))
        return pd.DatetimeIndex([pd.Timestamp(d) for d in sorted(days)])


class SuspendFromMissingBars(AbstractDateSet):
    """缺 bar 反推停牌（定案主源）：交易日在、parquet 无该票该日=停牌。"""

    def contains(self, order_book_id, dates):
        seq = self._bars_by_date(order_book_id)
        if seq is None:
            return None
        have = seq
        return [self._d_int(d) not in have for d in dates]

    @lru_cache(maxsize=256)
    def _bars_by_date(self, order_book_id):
        return None  # 子类/对拍时按票填；v0 返回 None=不宣称知道（保守不误停）

    @staticmethod
    def _d_int(d):
        if isinstance(d, (int, np.integer)):
            return int(d // 1000000) if int(d) > 100000000 else int(d)
        if isinstance(d, (_dt.date, _dt.datetime)):
            return d.year * 10000 + d.month * 100 + d.day
        return int(pd.Timestamp(str(d)).strftime("%Y%m%d"))


class StockdbSuspendSet(AbstractDateSet):
    """按票懒加载分钟线日期集合，缺=停牌。"""

    def __init__(self):
        self._cache = {}

    def _days(self, order_book_id) -> Optional[frozenset]:
        if order_book_id in self._cache:
            return self._cache[order_book_id]
        ts = _from_obid(order_book_id)
        code = ts.replace(".", "_")
        p = os.path.join(DB5, code + ".parquet")
        if not os.path.exists(p):
            self._cache[order_book_id] = None
            return None
        d = pd.read_parquet(p, columns=["date"])
        days = frozenset(int(str(x)) for x in d["date"].unique())
        self._cache[order_book_id] = days
        return days

    def contains(self, order_book_id, dates):
        days = self._days(order_book_id)
        if days is None:
            return None
        return [SuspendFromMissingBars._d_int(x) not in days for x in dates]


class StockdbDataSource(BaseDataSource):
    def __init__(self, base_config, market=MARKET.CN):
        base_config.data_bundle_path = os.path.join(os.path.dirname(__file__), "bundle")
        super().__init__(base_config, market)
        self.register_day_bar_store(INSTRUMENT_TYPE.CS, StockdbDayStore(), market)
        self.register_calendar_store(TRADING_CALENDAR_TYPE.CN_STOCK, StockdbCalendarStore())
        self.append_suspend_date_set(StockdbSuspendSet())
        # v0 交易分钟：交易所标准时段（5min bar-结束标签）
        self._minutes = {}

    def get_trading_minutes_for(self, instrument, trading_dt):
        d = _dt.datetime(trading_dt.year, trading_dt.month, trading_dt.day)
        mins = []
        for h0, m0, h1, m1 in [(9, 35, 11, 30), (13, 5, 15, 0)]:
            t = d.replace(hour=h0, minute=m0)
            end = d.replace(hour=h1, minute=m1)
            while t <= end:
                mins.append(t)
                t += _dt.timedelta(minutes=5)
        return mins


class StockdbPriceBoard(AbstractPriceBoard):
    def get_last_price(self, order_book_id):
        return np.nan

    def get_limit_up(self, order_book_id):
        return np.nan

    def get_limit_down(self, order_book_id):
        return np.nan

    def get_round_lot(self, order_book_id):
        return 100


class StockdbMod(AbstractMod):
    def start_up(self, env, mod_config):
        env.data_proxy = StockdbDataSource(env.config.base, MARKET.CN)
        env.price_board = StockdbPriceBoard()


def load_mod():
    return StockdbMod()
