#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘前补数3: 抓国常会算力网/数字乡村/伊朗等关键要闻详情. 只读."""
import urllib.request, json, traceback

def get(url, ref="https://kuaixun.eastmoney.com/", enc="utf-8"):
    req = urllib.request.Request(url, headers={"Referer": ref, "User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=25).read().decode(enc, "ignore")

seen = set()
KW = ["算力网", "国常会", "数字乡村", "伊朗", "霍尔木兹", "油价", "沙特", "PCB", "英伟达", "北证50", "解禁", "生猪", "存储"]
for pid in (101, 102, 103, 104):
    for page in (1, 2):
        try:
            txt = get(f"https://newsapi.eastmoney.com/kuaixun/v1/getlist_{pid}_ajaxResult_50_{page}_.html")
            d = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
            for it in (d.get("LivesList") or []):
                title = it.get("title", "")
                key = title[:30]
                if key in seen:
                    continue
                seen.add(key)
                if any(k in title for k in KW):
                    print(f"[{it.get('showtime','')[:16]}] {title}")
                    print(f"   {it.get('digest','')[:400]}\n")
        except Exception as e:
            print(f"  pid{pid}p{page} 失败: {type(e).__name__}")
print("total unique titles:", len(seen))
