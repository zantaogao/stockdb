import json, urllib.request, collections, os
os.chdir('/Users/zantao/.hermes/stockdb')
# 1) 今天上午指数分钟走势（取整点采样）
for code in ["sh000001", "sz399006"]:
    url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={code}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=8).read().decode("utf-8", "ignore"))
    try:
        mins = d["data"][code]["data"]["data"]
    except Exception:
        print(code, "keys", list(d.get("data", {}).get(code, {}).keys())); continue
    prev = d["data"][code]["qt"][code][4]
    prev = float(prev)
    pts = {}
    for m in mins:
        t, p = m.split()[0], float(m.split()[1])
        pts[t] = p
    for t in ["0930","0935","0945","1000","1015","1030","1045","1100","1115","1130"]:
        if t in pts:
            print(code, t, round(pts[t],2), f"{(pts[t]/prev-1)*100:+.2f}%")
    hi = max(float(m.split()[1]) for m in mins); lo = min(float(m.split()[1]) for m in mins)
    hit = [m.split()[0] for m in mins if float(m.split()[1])==hi][0]
    lot = [m.split()[0] for m in mins if float(m.split()[1])==lo][0]
    print(code, f"上午高点{hi:.2f}(+{(hi/prev-1)*100:.2f}%)@{hit} 低点{lo:.2f}({(lo/prev-1)*100:+.2f}%)@{lot}")
    print()

# 2) 今天上午意见分类统计
cnt = collections.Counter(); codes_by = collections.defaultdict(list)
for line in open("analysis/opinion_log.jsonl"):
    try: r = json.loads(line)
    except: continue
    ts = r.get("ts","")
    if ts.startswith("2026-09-22T") and ("09:" in ts or "10:" in ts or "11:0" in ts or "11:1" in ts or "11:2" in ts):
        k = r.get("key","").split("|")[0]
        cnt[k] += 1
        codes_by[k].append((r.get("code"), r.get("name")))
print(cnt)
for k, v in codes_by.items():
    uniq = {c for c in v if c is not None}
    print(k, "涉及票数", len(uniq), sorted(uniq))
