#!/usr/bin/env python3
# 隔夜美股个股 sina 直连重试（akshare py_mini_racer 坏掉时的绕行）
import urllib.request, json, time
syms = ['NVDA','MSFT','AAPL','TSLA','META','GOOG','AMZN','AVGO','MU','TSM','ASML','INTC','AMD','BABA','KWEB','XPEV','NIO','LI']
for s in syms:
    try:
        url = f"https://stock.finance.sina.com.cn/usstock/api/jsonp_v2.php/var%20_{s}/US_MinKService.getDailyK?symbol={s}"
        req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn'})
        raw = urllib.request.urlopen(req, timeout=15).read().decode('gbk', 'ignore')
        js = raw[raw.index('['):raw.rindex(']')+1]
        data = json.loads(js)
        d = data[-2:]
        if len(d) >= 2:
            c0, c1 = float(d[0]['c']), float(d[1]['c'])
            print(f"{s}: {c1} {(c1/c0-1)*100:+.2f}% [{d[1]['d']}] (prev {c0} {d[0]['d']})")
        else:
            print(f"{s}: 数据不足 {len(d)}")
    except Exception as e:
        print(f"{s}: 失败 {type(e).__name__} {e}")
    time.sleep(0.3)
