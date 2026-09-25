import urllib.request
url = "https://hq.sinajs.cn/list=s_sh000001,s_sz399001"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"})
d = urllib.request.urlopen(req, timeout=8).read().decode("gbk","ignore")
print(d)
