# 盘前补数v2：美股个股直连新浪（akshare py_mini_racer 坏: dlsym mr_eval_context）
import requests, json, time

syms = {'NVDA':'usNVDA','MSFT':'usMSFT','AAPL':'usAAPL','TSLA':'usTSLA','META':'usMETA',
        'GOOG':'usGOOG','AMZN':'usAMZN','AVGO':'usAVGO','MU':'usMU','TSM':'usTSM',
        'ASML':'usASML','INTC':'usINTC','AMD':'usAMD','BABA':'usBABA','KWEB':'usKWEB',
        'XPEV':'usXPEV','NIO':'usNIO','LI':'usLI'}

HDR = {'Referer':'https://finance.sina.com.cn','User-Agent':'Mozilla/5.0'}
url = ('https://stock.finance.sina.com.cn/usstock/api/jsonp_v2.php/x/US_MinKService.getDailyK'
       '?symbol={s}&___qn=3')

def one(name, s):
    try:
        r = requests.get(url.format(s=s), headers=HDR, timeout=15)
        t = r.text
        i = t.find('=(')
        j = t.rfind(')')
        data = json.loads(t[i+1:j].rstrip(';'))
        if not isinstance(data, list) or len(data) < 2:
            return f'  {name}: FAIL(short {t[:60]})'
        a, b = data[-2], data[-1]
        pct = (float(b['c'])/float(a['c'])-1)*100
        return f"  {name}: close {b['c']} {pct:+.2f}% [{b['d']}]"
    except Exception as e:
        return f'  {name}: FAIL({type(e).__name__} {str(e)[:60]})'

for n, s in syms.items():
    print(one(n, s), flush=True)
    time.sleep(0.2)

# 人民币：直连新浪即期
try:
    r = requests.get('https://hq.sinajs.cn/list=fx_susdcny,fx_seurusdcny', headers=HDR, timeout=10)
    r.encoding = 'gbk'
    print('FX:', r.text.strip())
except Exception as e:
    print('FX FAIL', e)
