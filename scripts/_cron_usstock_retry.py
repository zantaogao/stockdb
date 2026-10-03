# 盘前补数：美股个股 + 人民币（步骤2失败段的绕行重试）
import traceback
import akshare as ak
import concurrent.futures as _cf

syms = ['NVDA','MSFT','AAPL','TSLA','META','GOOG','AMZN','AVGO','MU','TSM','ASML','INTC','AMD',
        'BABA','KWEB','XPEV','NIO','LI']

def _us_one(s):
    try:
        df = ak.stock_us_daily(symbol=s, adjust='')
        r = df.tail(3)
        pct = (r.iloc[-1]['close']/r.iloc[-2]['close']-1)*100
        return f"  {s}: {r.iloc[-1]['close']} {pct:+.2f}% [{str(r.iloc[-1]['date'])[:10]}]"
    except Exception as e:
        return f"  {s}: FAIL({type(e).__name__}: {str(e)[:80]})"

with _cf.ThreadPoolExecutor(4) as ex:
    for line in ex.map(_us_one, syms):
        print(line, flush=True)

# 一次 traceback 样本
try:
    ak.stock_us_daily(symbol='NVDA')
    print('NVDA-retry: OK now')
except Exception:
    print('NVDA-traceback:')
    print(traceback.format_exc()[-1500:])

# 人民币中间价/即期
for fn, name in [(lambda: ak.fx_spot_quote(), 'fx_spot_quote'),
                 (lambda: ak.currency_boc_sina(symbol='美元', start_date='20260920', end_date='20260928'), 'boc')]:
    try:
        d = fn()
        print('---', name, 'rows', len(d))
        print(d.tail(3).to_string())
    except Exception:
        print('---', name, 'FAIL', traceback.format_exc(limit=1)[-200:])
