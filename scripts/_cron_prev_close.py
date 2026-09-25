import duckdb, json, sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.prices import fetch_prices_batch

codes = ['688659','003027','002875','300500','300908','300982','002942','301276','002809','603382','300556','301050','688681','603080']
tdu = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
suff = lambda c: c + ('.SH' if c.startswith(('6','9')) else '.SZ')
q = "SELECT ts_code, close FROM (SELECT ts_code, close, ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn FROM daily WHERE ts_code IN (%s)) WHERE rn=1" % ','.join("'" + suff(c) + "'" for c in codes)
prev = {r[0][:6]: float(r[1]) for r in tdu.execute(q).fetchall()}
live = fetch_prices_batch(codes)
for c in codes:
    p, l = prev.get(c), live.get(c)
    if p and l:
        print(c, 'prev=%.2f live=%.2f chg=%.2f%%' % (p, l, (l/p-1)*100))
    else:
        print(c, 'prev=%s live=%s' % (p, l))
