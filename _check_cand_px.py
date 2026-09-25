import sys
sys.path.insert(0, '.')
import duckdb
from core.prices import fetch_prices_batch

codes = ['600137','300100','688638','001256','603079','688175','300539','301131','301632','688360']
rtp = fetch_prices_batch(codes)
td = duckdb.connect('tushare.db', read_only=True)
prev = {r[0].split('.')[0]: float(r[1]) for r in td.execute(
    "SELECT ts_code, close FROM daily WHERE trade_date=(SELECT MAX(trade_date) FROM daily)").fetchall()}
for c in codes:
    px = rtp.get(c)
    pv = prev.get(c)
    chg = (px/pv-1)*100 if px and pv else None
    print(c, 'live=', px, 'prev=', pv, 'chg%=', round(chg,2) if chg is not None else None)