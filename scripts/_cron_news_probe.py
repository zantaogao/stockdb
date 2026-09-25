#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时：补拉快讯（同花顺+sina 7x24），并筛选半导体/存储相关线索。"""
import urllib.request, json, re, sys

def ths_news():
    out = []
    try:
        url = "https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&tag=&track=website&pagesize=100"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore"))
        for it in d.get("data", {}).get("list", []):
            out.append(("[ths] " + str(it.get("title", "")) + " | " + str(it.get("digest", "")))[:300])
    except Exception as e:
        out.append("THS_FAIL " + repr(e))
    return out

def sina_news():
    out = []
    try:
        url = "https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=100&zhibo_id=152&tag_id=0&dire=f&dpc=1"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore"))
        for it in d.get("result", {}).get("data", {}).get("feed", {}).get("list", []):
            txt = str(it.get("rich_text", ""))[:300]
            ts = str(it.get("create_time", ""))[11:19]
            out.append("[sina %s] %s" % (ts, txt))
    except Exception as e:
        out.append("SINA_FAIL " + repr(e))
    return out

rows = ths_news() + sina_news()
seen = set()
print("TOTAL", len(rows))
kw = sys.argv[1] if len(sys.argv) > 1 else "半导体|芯片|存储|美光|阿斯麦|ASML|铠侠|台积电|晶圆|海力士|三星|英伟达|算力|光模块|光通信|贵金属|黄金|原油|美联储|降息|关税|光刻"
for r in rows:
    if r in seen:
        continue
    seen.add(r)
    if re.search(kw, r):
        print(r.replace("\n", " ")[:260])
