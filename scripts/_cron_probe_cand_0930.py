import duckdb, sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.prices import fetch_prices_batch
t = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
codes = ['002253','300381','603900','688737','603488','600955','300066','603077','601012','002368','600416','688576','603567']
rtp = fetch_prices_batch(codes)
for c in codes:
    rows = t.execute(
        "SELECT trade_date, close FROM ("
        "SELECT trade_date, close, ROW_NUMBER() OVER (ORDER BY trade_date DESC) rn "
        "FROM daily WHERE ts_code LIKE ?) WHERE rn=1", (c + '%',)).fetchall()
    prev = float(rows[0][1]) if rows else None
    px = rtp.get(c)
    if prev and px:
        print(c, 'prev_close=', prev, 'now=', px, 'intraday_chg=%' + str(round((px/prev-1)*100, 2)))
t.close()
