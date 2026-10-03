# 盘前0928：直连新浪拉18只美股个股（akshare py_mini_racer dlsym 坏的绕行）
import requests, json, time, re

syms = ['NVDA','MSFT','AAPL','TSLA','META','GOOG','AMZN','AVGO','MU','TSM','ASML','INTC','AMD',
        'BABA','KWEB','XPEV','NIO','LI']
HDR = {'Referer': 'https://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'}

def daily_k(s):
    url = ('https://stock.finance.sina.com.cn/usstock/api/jsonp_v2.php/var%20_' + s +
           '/US_MinKService.getDailyK?symbol=' + s.lower() + '&___qn=3')
    r = requests.get(url, headers=HDR, timeout=15)
    t = r.text
    i = t.find('((')
    j = t.rfind(')')
    if i < 0:
        return None, t[:80]
    arr = t[i+1:j].rstrip(';')
    return json.loads(arr), None

for s in syms:
    try:
        d, err = daily_k(s)
        if d is None:
            print(f'{s}: nojson {err}'); continue
        a, b = d[-2], d[-1]
        pct = (float(b['c'])/float(a['c'])-1)*100
        print(f"{s}: {b['c']} {pct:+.2f}% [{b['d']}] (prev {a['c']} @{a['d']})")
    except Exception as e:
        print(f'{s}: FAIL {type(e).__name__} {str(e)[:60]}')
    time.sleep(0.2)
