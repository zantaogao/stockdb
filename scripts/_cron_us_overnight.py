#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时：拉隔夜美股18只 + 汇率（sina hq），供盘前报告补数据。"""
import urllib.request
import json

SYMS = {
    "NVDA": "gb_nvda", "MSFT": "gb_msft", "AAPL": "gb_aapl", "TSLA": "gb_tsla",
    "META": "gb_meta", "GOOG": "gb_googl", "AMZN": "gb_amzn", "AVGO": "gb_avgo",
    "MU": "gb_mu", "TSM": "gb_tsm", "ASML": "gb_asml", "INTC": "gb_intc",
    "AMD": "gb_amd", "BABA": "gb_baba", "KWEB": "gb_kweb", "XPEV": "gb_xpev",
    "NIO": "gb_nio", "LI": "gb_li",
}

url = "https://hq.sinajs.cn/list=" + ",".join(SYMS.values())
req = urllib.request.Request(url, headers={
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0",
})
raw = urllib.request.urlopen(req, timeout=25).read().decode("gbk", "ignore")
print("=== US STOCKS (sina gb_) ===")
for line in raw.strip().split("\n"):
    line = line.strip()
    if not line:
        continue
    try:
        code = line.split("=")[0].split("_")[-1].replace('"', '')
        vals = line.split('"')[1].split(",")
    except Exception as e:
        print("PARSE_FAIL", line[:120], e)
        continue
    # sina gb format: name, current, pct%, date, change, open, high, low, 52wh, 52wl, volume, ...
    name, cur, pct = vals[0], vals[1], vals[2]
    date = vals[3] if len(vals) > 3 else "?"
    chg = vals[4] if len(vals) > 4 else "?"
    print(f"{code.upper():6s} {name:22s} 现价 {cur:>10s} 涨跌 {chg:>8s} ({pct:>7s}%) 日期 {date}")

print()
print("=== FX (sina) ===")
fx = "fx_susdcny,fx_seurcny,fx_sjpycny,fx_sgbpcny,fx_susdjpy,fx_susdhkd"
req2 = urllib.request.Request("https://hq.sinajs.cn/list=" + fx, headers={
    "Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"})
raw2 = urllib.request.urlopen(req2, timeout=25).read().decode("gbk", "ignore")
for line in raw2.strip().split("\n"):
    if line.strip():
        print(line.strip()[:260])
