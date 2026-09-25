import subprocess
code = """
import akshare as ak
syms = ['NVDA','MSFT','AAPL','TSLA','META','GOOG','AMZN','AVGO','MU','TSM','ASML','INTC','AMD','BABA','KWEB','XPEV','NIO','LI']
import concurrent.futures as cf
def one(s):
    try:
        df = ak.stock_us_daily(symbol=s)
        r = df.tail(2)
        pct = (r.iloc[-1]['close']/r.iloc[-2]['close']-1)*100 if len(r)>1 else float('nan')
        return f"{s} {r.iloc[-1]['close']} {pct:+.2f}% [{r.iloc[-1]['date']}]"
    except Exception as e:
        return f"{s} FAIL {type(e).__name__}"
with cf.ThreadPoolExecutor(6) as ex:
    for line in ex.map(one, syms):
        print(line)
"""
r = subprocess.run(['/usr/bin/python3','-B','-c',code], capture_output=True, text=True, timeout=240, env={'PATH':'/usr/bin:/bin','HOME':'/Users/zantao'})
print(r.stdout[-2500:] or r.stderr[-800:])