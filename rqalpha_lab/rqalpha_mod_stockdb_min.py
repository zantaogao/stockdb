# -*- coding: utf-8 -*-
"""rqalpha 分钟线撮合 mod（Task 3.4）。

路线（实锤定案，见 git 54ab7a6 / bd13896）：
- 日线：bundle/ 原生 BaseDataSource（撮合已对账打通）
- 分钟：bundle_min/{obid}.npz（bar-结束口径；datetime=YYYYMMDDHHMMSS 午夜基+时分秒，
  与 convert_dt_to_int 同口径；volume 股、amount 元——parquet 原生不转换）
- 注入点（main.py:150 实锤）：mod.start_up() 早于 set_data_source；`hasattr(env,"data_source")`
  为假才建 BaseDataSource → 本 mod 在 start_up 里 env.set_data_source(装饰器)，
  原生就不会再建，1d 行为逐字节不变。

装饰器分工：
- frequency=='1m'：get_bar/get_trading_minutes_for/available_data_range/history_bars 读 npz；
  其余 attribute 全委托 BaseDataSource（__getattr__）。
- available_data_range('1m') 返回 npz 覆盖区间——原生只认 ['tick','1d'] 返回 None，
  main.py:52 unpack 崩，这是 1m 能起跑的关键闸。
- 49 根日（11:30 半根）：撮合按事件分钟对齐 npz 时间戳，多出的半根自然不匹配，无需特判。
"""
import os
import datetime as _dt

import numpy as np

from rqalpha.interface import AbstractDataSource, AbstractMod
from rqalpha.data.base_data_source import BaseDataSource
from rqalpha.environment import Environment
from rqalpha.utils.datetime_func import convert_dt_to_int

MIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bundle_min")


class _MinuteStore(object):
    """per-stock npz，LRU 缓存（键序弹出，无第三方依赖）。"""

    def __init__(self, max_cached=64):
        self._cache = {}
        self._max = max_cached

    def bars(self, order_book_id):
        arr = self._cache.get(order_book_id)
        if arr is not None:
            return arr
        p = os.path.join(MIN_DIR, order_book_id + ".npz")
        if not os.path.exists(p):
            return None
        arr = np.load(p)["bars"]
        if len(self._cache) >= self._max:
            self._cache.pop(next(iter(self._cache)))
        self._cache[order_book_id] = arr
        return arr

    def days(self, order_book_id):
        b = self.bars(order_book_id)
        if b is None:
            return frozenset()
        return frozenset((b["datetime"] // 1000000).tolist())


class MinuteOverlayDataSource(BaseDataSource):
    """继承 BaseDataSource：1d 全原生，1m 读 npz（v2：main.py:151 直接实例化本类）。"""

    def __init__(self, config, market=None):
        kwargs = {"market": market} if market is not None else {}
        BaseDataSource.__init__(self, config, **kwargs)
        self._min = _MinuteStore()
        s, e = None, None
        for f in os.listdir(MIN_DIR):
            if f.endswith(".npz"):
                with np.load(os.path.join(MIN_DIR, f), mmap_mode="r") as z:
                    a = z["bars"]
                    if len(a):
                        s0, e0 = int(a["datetime"][0]), int(a["datetime"][-1])
                        s = s0 if s is None else min(s, s0)
                        e = e0 if e is None else max(e, e0)
        self._min_start, self._min_end = s, e

    # ---- 1m 专属 ----
    def available_data_range(self, frequency):
        if frequency == "1m":
            return (_dt.datetime.strptime(str(self._min_start // 1000000), "%Y%m%d").date(),
                    _dt.datetime.strptime(str(self._min_end // 1000000), "%Y%m%d").date())
        return BaseDataSource.available_data_range(self, frequency)

    def get_bar(self, instrument, dt, frequency):
        if frequency == "1m":
            b = self._min.bars(instrument.order_book_id)
            if b is None:
                return None
            dt_int = np.int64(convert_dt_to_int(dt))
            pos = b["datetime"].searchsorted(dt_int)
            if pos >= len(b) or b["datetime"][pos] != dt_int:
                return None
            return b[pos]
        return BaseDataSource.get_bar(self, instrument, dt, frequency)

    def get_trading_minutes_for(self, instrument, trading_dt):
        d = trading_dt.year * 10000 + trading_dt.month * 100 + trading_dt.day
        b = self._min.bars(instrument.order_book_id)
        if b is None or d not in frozenset((b["datetime"] // 1000000).tolist()):
            return set()
        day = b[b["datetime"] // 1000000 == d]
        out = set()
        for v in day["datetime"]:
            tod = int(v) % 1000000
            out.add(_dt.datetime(trading_dt.year, trading_dt.month, trading_dt.day,
                                 tod // 10000, (tod // 100) % 100, tod % 100))
        return out

    def history_bars(self, instrument, bar_count, frequency, fields, dt,
                     skip_suspended=True, include_now=False,
                     adjust_type="pre", adjust_orig=None):
        if frequency == "1m":
            b = self._min.bars(instrument.order_book_id)
            if b is None:
                return None
            pos = b["datetime"].searchsorted(np.int64(convert_dt_to_int(dt)),
                                             side="right" if include_now else "left")
            sl = b[max(0, pos - bar_count):pos]
            if len(sl) == 0:
                return None
            if isinstance(fields, str):
                return np.asarray(sl[fields])
            fl = list(fields)
            out = np.asarray([sl[f] for f in fl]).T
            return out[0] if len(fl) == 1 else out
        return BaseDataSource.history_bars(self,instrument, bar_count, frequency, fields, dt,
                                       skip_suspended=skip_suspended, include_now=include_now,
                                       adjust_type=adjust_type, adjust_orig=adjust_orig)




class StockdbMinMod(AbstractMod):
    def __init__(self):
        self._mod_config = None

    def start_up(self, env, mod_config):
        # main.py:150 `if not hasattr(env, "data_source")` 在 mod_handler.start_up() 之后，
        # 换掉 main 模块引用的 BaseDataSource 名字，原生实例化点即产出本类。
        self._mod_config = mod_config
        import rqalpha.main as _m
        _m.BaseDataSource = MinuteOverlayDataSource

    def tear_down(self, exc):
        pass


def load_mod():
    return StockdbMinMod()
