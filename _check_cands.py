import sys
sys.path.insert(0, '.')
from core.prices import fetch_price_live
import duckdb

tdu = duckdb.connect('tushare.db', read_only=True)
cands = ['002866', '000990', '603863', '688273', '605286', '600137', '300100', '688638', '001256', '603079']
for c in cands:
    try:
        px, chg = fetch_price_live(c)
    except Exception as e:
        px, chg = None, repr(e)
    r = tdu.execute(
        "SELECT close FROM daily WHERE ts_code LIKE ? ORDER BY trade_date DESC LIMIT 4", (c + '.%',)).fetchall()
    closes = [float(x[0]) for x in r][::-1]
    d3 = (closes[-1] / closes[0] - 1) * 100 if len(closes) >= 4 else None
    name = tdu.execute("SELECT name FROM stock_basic WHERE ts_code LIKE ?", (c + '.%',)).fetchone()
    print(c, name[0] if name else '?', 'live_chg=%s' % chg, 'prev3d_ret=%s' % (round(d3, 2) if d3 is not None else None), 'px=%s' % px)