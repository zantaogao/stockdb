#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘前补数: A50实时(新浪外盘) + 东财7x24快讯(周末动态). 只读."""
import urllib.request, json, traceback, datetime

print("NOW:", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S %a"))

def get(url, ref="https://finance.sina.com.cn/", enc="utf-8"):
    req = urllib.request.Request(url, headers={"Referer": ref, "User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=20).read().decode(enc, "ignore")

# --- 1. A50 / 恒指期货 / 外盘实时 (新浪 hf_) ---
try:
    syms = ["hf_CHA50CFD", "hf_NK", "hf_HSI"]
    raw = get("https://hq.sinajs.cn/list=" + ",".join(syms), enc="gbk")
    print("\n【新浪外盘实时】")
    for line in raw.strip().split("\n"):
        if '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        f = line.split('"')[1].split(",")
        if len(f) < 8:
            print(f"  {key}: 空/停报 -> {line[:80]}")
        else:
            print(f"  {key}: 现价{f[0]} 昨结{f[7] if len(f)>7 else '?'} 时间{f[-2]} {f[-1]}  原始前12={f[:12]}")
except Exception:
    print("A50实时失败:", traceback.format_exc(limit=1))

# --- 2. 东财7x24快讯 ---
for tag, url in [("EM102", "https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_50_1_.html"),
                 ("EM101", "https://newsapi.eastmoney.com/kuaixun/v1/getlist_101_ajaxResult_50_1_.html")]:
    try:
        txt = get(url, ref="https://kuaixun.eastmoney.com/")
        s = txt[txt.find("{"):txt.rfind("}") + 1]
        d = json.loads(s)
        items = d.get("LivesList") or d.get("livesList") or []
        print(f"\n【{tag} 东财快讯 {len(items)}条】")
        for it in items[:40]:
            t = (it.get("showtime") or "")[:16]
            print(f"  [{t}] {it.get('title','')} | {(it.get('digest') or '')[:120]}")
    except Exception:
        print(f"{tag} 失败:", traceback.format_exc(limit=1))
