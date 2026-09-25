import duckdb, os, glob, json
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
tdb = duckdb.connect('tushare.db', read_only=True)
rows = list(reversed(tdb.execute("SELECT trade_date, close, vol FROM daily WHERE ts_code='300779.SZ' ORDER BY trade_date DESC LIMIT 30").fetchall()))
if len(rows)>=20:
    closes=[r[1] for r in rows]; vols=[r[2] for r in rows]; close=closes[-1]
    ma20=sum(closes[-20:])/20; m=ma20
    sd=(sum((x-m)**2 for x in closes[-20:])/20)**0.5; up,lo=m+2*sd,m-2*sd
    print('300779.SZ 惠城环保 close=%.2f dev=%.1f boll=%.0f chg5=%.1f dist_hi=%.1f volr=%.2f'%(close,(close/ma20-1)*100,(close-lo)/(up-lo)*100,(close/closes[-6]-1)*100,(close/max(closes[-20:])-1)*100, vols[-1]/(sum(vols[-6:-1])/5)))
else:
    print('no rows for 300779.SZ:', rows[:3])
    r2 = tdb.execute("SELECT ts_code, MAX(trade_date), COUNT(*) FROM daily WHERE ts_code LIKE '300779%' GROUP BY ts_code").fetchall()
    print('like-query:', r2)
