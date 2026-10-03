import json, sqlite3
import duckdb

# 今日候选池（signal_date 20260924 合成分前15）
pool = ['600785','300970','300228','600594','603737','002208','688500','001366','600510','301167','000617','300732','603887','603113','300214']
held = ['001238','003027','300837','300881','300970','300982','301167','301276','603382','603409','688592','688659']

# 信号日收盘 vs 上一交易日收盘（判断信号日后是否下跌）
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
ts = lambda c: c + ('.SH' if c.startswith(('6','9')) else '.SZ')
for c in held:
    q = con.execute("SELECT trade_date, close FROM daily WHERE ts_code=? AND trade_date<='20260928' ORDER BY trade_date DESC LIMIT 3", (ts(c),)).fetchall()
    sig = [r for r in q if r[0] <= '20260924']
    if q and sig:
        print(c, 'latest', q[0], 'sigday', sig[0], 'chg_since_sig %.2f%%' % ((q[0][1]/sig[0][1]-1)*100))
    else:
        print(c, 'no data', q[:1])

# 新浪实时涨跌幅（今日盘中）
import akshare as ak
df = ak.stock_zh_a_spot_sina() if hasattr(ak,'stock_zh_a_spot_sina') else None
sina_codes = [s.replace('688','sh688').replace('301','sz301').replace('300','sz300') if False else ('sh' if c.startswith('6') else 'sz')+c for c in held]
try:
    import requests
    r = requests.get('https://hq.sinajs.cn/list=' + ','.join(sina_codes), headers={'Referer':'https://finance.sina.com.cn'}, timeout=10)
    for line, c in zip(r.text.strip().split('\n'), held):
        parts = line.split('"')[1].split(',')
        if len(parts) > 3:
            prev, cur = float(parts[2]), float(parts[3])
            if prev > 0:
                print('today', c, parts[0], 'pct %.2f%%' % ((cur/prev-1)*100), 'in_pool' if c in pool else 'NOT_IN_POOL')
except Exception as e:
    print('sina err', e)
