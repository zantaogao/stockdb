#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘前美股映射兜底: sina 美股实时快照 (gb_xxx). 只读, 不写库."""
import urllib.request

SYMS = ['NVDA','MSFT','AAPL','TSLA','META','GOOG','AMZN','AVGO','MU','TSM',
        'ASML','INTC','AMD','BABA','KWEB','XPEV','NIO','LI']

url = "https://hq.sinajs.cn/list=" + ",".join("gb_" + s.lower() for s in SYMS)
req = urllib.request.Request(url, headers={
    "Referer": "https://finance.sina.com.cn/",
    "User-Agent": "Mozilla/5.0",
})
raw = urllib.request.urlopen(req, timeout=20).read().decode("gbk", "ignore")
for line in raw.strip().split("\n"):
    if '"' not in line:
        continue
    key = line.split("=")[0].split("_")[-1].upper()
    body = line.split('"')[1]
    f = body.split(",")
    if len(f) < 10:
        print(f"  {key}: 未获取(空)")
        continue
    # gb_ 字段: 0=名称 1=最新价 2=涨跌幅% 3=行情时间 4=涨跌额 5=开盘 6=最高 7=最低 ...
    try:
        name, price, pct, t = f[0], float(f[1]), float(f[2]), f[3]
        print(f"  {key}: {name} {price:.2f} {pct:+.2f}% [{t}]")
    except Exception as e:
        print(f"  {key}: 解析失败({type(e).__name__}) 首字段={f[:4]}")
