import sys, collections
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')
import agent_trade_decision as m
ts = m._tushare()
codes = ['301276','603382','003027','688659','300500','300982','001238','300837','300881','301053','603409','688592']
rtp = m.fetch_prices_batch(codes)
prev = {}
for r in ts.execute("SELECT ts_code, close FROM daily WHERE trade_date=(SELECT MAX(trade_date) FROM daily)").fetchall():
    prev[r[0].split('.')[0]] = float(r[1])
for c in codes:
    p = rtp.get(c); y = prev.get(c)
    print(c, 'now', p, '昨收', y, '今chg %.2f%%' % ((p/y-1)*100) if p and y else 'NA')
print('market:', m.market_state(m._conn(), ts))
