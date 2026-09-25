#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指数 09-11 / 09-14 开收盘，用于复盘周一盘前研判（平开偏弱 vs 实际）。"""
import duckdb

con = duckdb.connect("/Users/zantao/.hermes/stockdb/tushare.db", read_only=True)
cols = con.execute("DESCRIBE index_daily").fetchdf()
print("index_daily 列:", list(cols["column_name"]))
try:
    codes = [("000001.SH", "上证"), ("399001.SZ", "深成"), ("399006.SZ", "创业板"), ("000852.SH", "中证1000")]
    for code, name in codes:
        df = con.execute(
            "SELECT trade_date, open, high, low, close, pct_chg FROM index_daily WHERE ts_code=? AND trade_date IN ('20260911','20260914') ORDER BY trade_date",
            [code]).fetchdf()
        if len(df) == 0:
            print(f"{name}: 无数据")
            continue
        for _, r in df.iterrows():
            print(f"{name:6s} {r['trade_date']} 开{r['open']:9.2f} 高{r['high']:9.2f} 低{r['low']:9.2f} 收{r['close']:9.2f} {r['pct_chg']:+6.2f}%")
except Exception as e:
    print("ERR", e)
con.close()
