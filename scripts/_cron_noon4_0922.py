import os, json, urllib.request
os.chdir('/Users/zantao/.hermes/stockdb')
# 实时指数快照（腾讯行情，只读）
codes = "sh000001,sz399001,sz399006,sh000852"
url = "https://qt.gtimg.cn/q=" + codes
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
data = urllib.request.urlopen(req, timeout=8).read().decode("gbk", "ignore")
for line in data.strip().split(";"):
    line = line.strip()
    if not line: continue
    f = line.split('"')[1].split("~")
    # f[1]=name f[3]=price f[4]=yesterday close f[31]=change f[32]=pct f[6]=vol(手) f[37]? amount
    print(f[2], f[1], "现价", f[3], "昨收", f[4], "涨跌%", f[32], "时间", f[30])
