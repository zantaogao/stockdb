import urllib.request
url = "https://qt.gtimg.cn/q=sh000001,sz399001"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
d = urllib.request.urlopen(req, timeout=8).read().decode("gbk","ignore")
for line in d.strip().split(";"):
    if '"' not in line: continue
    f = line.split('"')[1].split("~")
    # f[36]=成交额(元) or 手? print a few fields with labels for inspection
    print(f[1], "f36=", f[36], "f37=", f[37])
