#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""补：09-14 当日涨跌幅（持仓+关键票OHLC）+ 指数开收盘（若有表）。"""
import duckdb

con = duckdb.connect("/Users/zantao/.hermes/stockdb/tushare.db", read_only=True)
tabs = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
print("含 index 的表:", [t for t in tabs if "index" in t.lower()])
print("含 daily 的表:", [t for t in tabs if "daily" in t.lower()])
print()

WATCH = [("688636", "智明达(持)"), ("301557", "常友科技(持)"), ("301237", "和顺科技(持)"),
         ("688093", "世华科技(持)"), ("002454", "松芝股份(持)"), ("603966", "法兰泰克(持)"),
         ("301093", "华兰股份(持)"), ("603202", "天有为(持)"), ("601615", "明阳智能(持)"),
         ("688186", "广大特材(持)"), ("001332", "锡装股份(持)"), ("300658", "延江股份(持)"),
         ("301110", "青木科技(持)"), ("300986", "志特新材(持)"), ("605598", "上海港湾(持)"),
         ("600104", "上汽集团"), ("000625", "长安汽车"), ("601872", "招商轮船"),
         ("601808", "中海油服"), ("600583", "海油工程"), ("300308", "中际旭创"),
         ("300502", "新易盛"), ("603986", "兆易创新"), ("002080", "中材科技"),
         ("002491", "通鼎互联"), ("688377", "迪威尔"), ("688073", "毕得医药")]
print("09-14 当日表现（附09-14 OHLC）:")
for code, name in WATCH:
    df = con.execute("SELECT trade_date,open,high,low,close,pct_chg FROM daily WHERE ts_code LIKE ? || '%' AND trade_date='20260914'", [code]).fetchdf()
    if len(df) == 0:
        print(f"  {name:16s} 无数据")
        continue
    r = df.iloc[0]
    print(f"  {name:16s} 开{r['open']:8.2f} 高{r['high']:8.2f} 低{r['low']:8.2f} 收{r['close']:8.2f} 当日{r['pct_chg']:+6.2f}%")
con.close()
