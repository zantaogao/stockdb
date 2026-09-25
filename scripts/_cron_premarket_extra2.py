#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘前补数2: 人民币汇率(多源尝试) + 东财芯片暗盘文章详情. 只读."""
import urllib.request, json, traceback

def get(url, ref="https://finance.eastmoney.com/", enc="utf-8"):
    req = urllib.request.Request(url, headers={"Referer": ref, "User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=20).read().decode(enc, "ignore")

print("【汇率】")
for sym in ["fx_susdcny", "fx_susdcnh", "USDCNY", "fx_susdcny"]:
    try:
        raw = get("https://hq.sinajs.cn/list=" + sym, ref="https://finance.sina.com.cn/", enc="gbk")
        body = raw.split('"')[1] if '"' in raw else ""
        print(f"  sina {sym}: {body[:160]}")
    except Exception as e:
        print(f"  sina {sym}: 失败 {e}")

try:
    df = get("https://push2.eastmoney.com/api/qt/ulist.np/get?fields=f1,f2,f3,f4,f12,f13,f14"
             "&secids=133.USDCNH,119.USDCNY,100.UDI,101.GC00Y,101.CL00Y,101.HG00Y",
             ref="https://quote.eastmoney.com/")
    d = json.loads(df)
    for it in (d.get("data") or {}).get("diff") or []:
        print(f"  东财 {it.get('f14')} ({it.get('f12')}): 最新{it.get('f2')} 涨跌{it.get('f4')} 涨跌幅{it.get('f3')}%")
except Exception:
    print("  东财汇率失败:", traceback.format_exc(limit=1))

print("\n【芯片暗盘/周末要闻详情】")
try:
    txt = get("https://newsapi.eastmoney.com/kuaixun/v1/getlist_101_ajaxResult_50_1_.html",
              ref="https://kuaixun.eastmoney.com/")
    d = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
    for it in (d.get("LivesList") or []):
        t = it.get("title", "")
        if any(k in t for k in ["芯片", "暗盘", "CPI", "加息", "算力", "国常会", "指数成份"]):
            print(f"  [{it.get('showtime','')[:16]}] {t}")
            print(f"     {it.get('digest','')[:600]}")
except Exception:
    print("  失败:", traceback.format_exc(limit=1))
