#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A股侧板块代理核验：算力/半导体/光模块、贵金属、油气油服、汽车链、电子布、小金属、港股相关。"""
import duckdb

GROUPS = {
    "AI算力/光模块": [("300308", "中际旭创"), ("300502", "新易盛"), ("002463", "沪电股份"), ("300476", "胜宏科技"), ("002916", "深南电路")],
    "半导体": [("603986", "兆易创新"), ("002371", "北方华创"), ("688981", "中芯国际"), ("688008", "澜起科技"), ("688041", "海光信息")],
    "存储/消费电子": [("002049", "紫光国微"), ("603501", "韦尔股份"), ("002475", "立讯精密"), ("002241", "歌尔股份")],
    "贵金属/有色": [("600547", "山东黄金"), ("601899", "紫金矿业"), ("000975", "山金国际"), ("600988", "赤峰黄金")],
    "小金属": [("600111", "北方稀土"), ("000960", "锡业股份"), ("002428", "云南锗业"), ("600259", "中稀有色")],
    "油气/油服/油运": [("601857", "中国石油"), ("600583", "海油工程"), ("601808", "中海油服"), ("601872", "招商轮船"), ("600026", "中远海能")],
    "汽车整车/零部件": [("600104", "上汽集团"), ("002594", "比亚迪"), ("000625", "长安汽车"), ("601127", "赛力斯"), ("002920", "德赛西威")],
    "电子布/玻纤": [("603256", "宏和科技"), ("002080", "中材科技"), ("600176", "中国巨石")],
    "医药/生物": [("600276", "恒瑞医药"), ("300760", "迈瑞医疗"), ("688278", "特宝生物")],
    "港股映射·互联网": [("00700", "腾讯控股"), ("09988", "阿里巴巴-W"), ("03690", "美团-W")],
}

con = duckdb.connect("/Users/zantao/.hermes/stockdb/tushare.db", read_only=True)
maxd = con.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
print("最新交易日:", maxd)
for g, lst in GROUPS.items():
    print()
    print(f"== {g} ==")
    for code, name in lst:
        df = con.execute(
            "SELECT trade_date, close, high FROM daily WHERE ts_code LIKE ? || '%' AND trade_date <= ? ORDER BY trade_date DESC LIMIT 22",
            [code, maxd]).fetchdf()
        if len(df) < 6:
            print(f"  {name:8s} 数据不足({len(df)})")
            continue
        df = df.sort_values("trade_date")
        closes = df["close"].tolist()
        highs = df["high"].tolist()
        last = closes[-1]
        c5 = (last / closes[-6] - 1) * 100
        c1 = (last / closes[-2] - 1) * 100
        hi20 = max(highs[-21:] if len(highs) >= 21 else highs)
        dist = (hi20 - last) / last * 100
        print(f"  {name:8s} {last:8.2f}  当日{c1:+6.2f}%  5日{c5:+6.2f}%  距20日高{dist:+6.2f}%")
con.close()
