#!/usr/bin/env python3
"""查杰理科技新股发行信息（东财接口）"""
import json
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0"}

def fetch(report):
    url = (f"https://datacenter-web.eastmoney.com/api/data/v1/get?reportName={report}"
           f"&columns=ALL&pageSize=300&pageNumber=1&sortColumns=NOTICE_DATE&sortTypes=-1")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())

for rpt in ["RPT_IPO_PREIPO", "RPT_IPO_APPEAL", "RPT_IPO_REGISTER", "RPT_IPO_ISSUE", "RPTA_APP_IPOAPPLY"]:
    try:
        d = fetch(rpt)
        data = (d.get("result") or {}).get("data") or []
        hits = [i for i in data if "杰理" in str(i.get("SECURITY_NAME_ABBR", "")) + str(i.get("COMPANY_NAME", ""))]
        print(f"== {rpt}: 总{len(data)}条, 命中{len(hits)} ==")
        for h in hits:
            print(json.dumps(h, ensure_ascii=False)[:800])
    except Exception as e:
        print(f"== {rpt}: 失败 {e} ==")
