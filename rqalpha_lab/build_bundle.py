# -*- coding: utf-8 -*-
"""bundle 构建器 v3（Task 3.2）：tushare.db(只读) → rqalpha_lab/bundle/。

6.4.0 实际 dtype（读自 site-packages/.../storages.py DayBarStore/SecuritiesDayBarStore，非文档）：
  datetime(i64) open close high low volume total_turnover limit_up limit_down
注意字段序是 open,close,high,low（close 在 high 前）。

产物：
  instruments.pk      list[dict]（stock_basic 全量，.XSHG/.XSHE）
  dates.npy           交易日历 = trade_cal_5min.json(360d) ∪ stock_daily distinct date
  stocks.h5           日线；vol×100(手→股)、amount×1000(千元→元)（单位经 a/(v*c)=0.001 实证）
  suspended_days.h5   缺 bar 反推停牌（定案主源；仅分钟线窗口 20250408-20260924 内标注）
"""
import os, pickle, json
import numpy as np
import pandas as pd
import h5py
import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLE = os.path.join(HERE, "bundle")
os.makedirs(BUNDLE, exist_ok=True)
ROOT = os.path.expanduser("~/.hermes/stockdb")
TUSHARE = os.path.join(ROOT, "tushare.db")
DB5 = os.path.join(ROOT, "minutes", "5min")
WIN = ("20250408", "20260924")

DAY_DTYPE = np.dtype([
    ("datetime", "<i8"), ("open", "<f8"), ("close", "<f8"),
    ("high", "<f8"), ("low", "<f8"),
    ("volume", "<f8"), ("total_turnover", "<f8"),
    ("limit_up", "<f8"), ("limit_down", "<f8"),
])
DTYPE_NAMES = DAY_DTYPE.names  # 结构化数组按名字赋值；arr[i] 返回0维标量不可用

con = duckdb.connect(TUSHARE, read_only=True)
rows = con.execute(
    "select ts_code, name, list_date from stock_basic where list_date is not null").fetchall()
sd_days = sorted(str(d)[:10].replace("-", "") for d in con.execute(
    "select distinct date from stock_daily").df()["date"])



cal5 = sorted(str(x)[:10].replace("-", "") for x in json.load(
    open(os.path.join(ROOT, "minutes", "trade_cal_5min.json"))))
cal = sorted(set(cal5) | set(sd_days))
print("日历: cal5=%d ∪ stock_daily=%d → %d 天" % (len(cal5), len(sd_days), len(cal)))

def to_obid(ts):
    c, e = ts.split(".")
    return c + (".XSHG" if e == "SH" else ".XSHE")

insts = []
for ts_code, name, list_date in rows:
    ld = str(list_date).replace("-", "")
    ob = to_obid(ts_code)
    insts.append({
        "order_book_id": ob, "symbol": name or ob,
        "listed_date": "%s-%s-%s" % (ld[:4], ld[4:6], ld[6:8]),
        "de_listed_date": "2099-12-31",
        "round_lot": 100, "type": "CS",
        "exchange": "SSE" if ob.endswith(".XSHG") else "SZSE",
        "industry_name": "未知", "industry_code": "I", "sector_code": "I",
        "board_type": ("ChiNext" if ts_code.startswith("300") else
                       "STAR" if ts_code.startswith("688") else "MainBoard"),
        "stock_type": "", "status": 0,
    })

with open(os.path.join(BUNDLE, "instruments.pk"), "wb") as f:
    pickle.dump(insts, f)
np.save(os.path.join(BUNDLE, "dates.npy"), np.array([int(d) for d in cal], dtype="<u8"))
# BaseDataSource 实际读 trading_dates.npy（data_source.py:103 _p('trading_dates.npy')），同名双份落盘
np.save(os.path.join(BUNDLE, "trading_dates.npy"), np.array([int(d) for d in cal], dtype="<u8"))

cal_arr = np.array([int(x) for x in cal], dtype="<i8")
n = 0
con = duckdb.connect(TUSHARE, read_only=True)
with h5py.File(os.path.join(BUNDLE, "stocks.h5"), "w") as hf, \
     h5py.File(os.path.join(BUNDLE, "suspended_days.h5"), "w") as hs:
    for ts_code, name, list_date in rows:
        ob = to_obid(ts_code)
        tab = None  # 每票一次批量取
        df = con.execute(
            "select d.date, d.open, d.close, d.high, d.low, d.volume, d.amount, "
            "       l.up_limit as limit_up, l.down_limit as limit_down "
            "from stock_daily d left join stk_limit l "
            "  on l.ts_code = d.stock_code || case when d.stock_code like '6%' or d.stock_code like '9%' then '.SH' else '.SZ' end "
            " and l.trade_date = strftime(d.date, '%Y%m%d') "
            "where d.stock_code=? and d.date>='1990-01-01' order by d.date",
            [ts_code[:6]]).df()
        if df is None or df.empty:
            continue
        keep = ["date", "open", "close", "high", "low", "volume", "amount"]
        if "limit_up" in df.columns:
            keep += ["limit_up", "limit_down"]
        df = df[keep].copy()
        arr = np.empty(len(df), dtype=DAY_DTYPE)
        dts = pd.to_datetime(df["date"].astype(str).str[:10])
        # datetime 口径 = YYYYMMDDHHMMSS 十进制整数（非 epoch 秒！读自 datetime_func.convert_date_to_int：
        # year*1e10+month*1e8+day*1e6[+hour*1e4+min*100+sec]）。日线用 15:00 收盘时刻。
        arr["datetime"] = (dts.dt.strftime("%Y%m%d").astype("<i8") * 1000000).values
        for i, col in enumerate(["open", "close", "high", "low"]):
            arr[DTYPE_NAMES[1 + i]] = df[col].astype(np.float64).values
        arr["volume"] = df["volume"].astype(np.float64).values * 100.0
        arr["total_turnover"] = df["amount"].astype(np.float64).values * 1000.0
        # limit_up/down：本地 stk_limit 真值（tushare 源, 8480 票覆盖; nan=引擎按无限制撮合）
        lu = df.get("limit_up")
        if lu is not None:
            arr["limit_up"] = lu.astype(np.float64).values
            arr["limit_down"] = df["limit_down"].astype(np.float64).values
        else:
            arr["limit_up"] = np.nan
            arr["limit_down"] = np.nan
        hf.create_dataset(ob, data=arr)
        # 缺 bar 反推（定案主源，口径 v2 0925 修正）：
        # ① 只在 daily 同日 vol>0 时不标（停牌必无日线成交；daily 有量=确凿非停牌，防回填尾窗误判）
        # ② daily 同日也无行/vol=0 → 视为停牌（真停牌 daily 亦无 bar 或 vol=0）
        d5 = os.path.join(DB5, ("sh_" if ts_code.startswith(("6", "9")) else "sz_") + ts_code[:6] + ".parquet")
        have = frozenset()
        if os.path.exists(d5):
            have = frozenset(
                __import__("pandas").read_parquet(d5, columns=["date"])["date"]
                .astype(str).str[:10].str.replace("-", "").unique())
        # daily 有量日集合（窗口内）
        traded = frozenset(
            str(x)[:10].replace("-", "") for x in
            df[df["volume"].astype("int64") > 0]["date"].astype(str).unique())
        listed_int = int(str(list_date).replace("-", ""))
        susp = [int(d) for d in cal
                if int(d) >= listed_int and WIN[0] <= d <= WIN[1]
                and d not in have and d not in traded]
        if susp:
            hs.create_dataset(ob, data=np.array(susp, dtype="<i8"))
        n += 1
con.close()
con.close()
# ---- indexes.h5: 指数日线（YYYYMMDD*1e6+150000 口径, volume×100, amount×1000）----
_con_idx = duckdb.connect(os.path.expanduser("~/.hermes/stockdb/tushare.db"), read_only=True)
_df_idx = _con_idx.execute("select index_code, date, open, close, high, low, volume, amount from index_daily order by index_code, date").df()
_con_idx.close()
with h5py.File(os.path.join(BUNDLE, "indexes.h5"), "w") as _hf:
    for _code, _g in _df_idx.groupby("index_code"):
        _a = np.empty(len(_g), dtype=DAY_DTYPE)
        _a["datetime"] = (pd.to_datetime(_g["date"].astype(str)).dt.strftime("%Y%m%d").astype("<i8")*1000000).values
        for _i,_col in enumerate(["open","close","high","low"]):
            _a[DTYPE_NAMES[1+_i]] = _g[_col].astype(float).values
        _a["volume"] = _g["volume"].astype(float).values*100
        _a["total_turnover"] = _g["amount"].astype(float).values*1000
        _hf.create_dataset(_code + (".XSHE" if _code.startswith("399") else ".XSHG"), data=_a)


print("stocks.h5: %d 票写入; suspend 窗口 %s-%s" % (n, WIN[0], WIN[1]))
