# 盘前0928：榜内票近3日涨幅与涨停检查
import duckdb
from collections import defaultdict
db = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
codes = ['000017.SZ','000019.SZ','000428.SZ','000430.SZ','000505.SZ','000523.SZ','000524.SZ','000533.SZ','000553.SZ','000554.SZ',
         '001225.SZ','003040.SZ','603900.SH','002942.SZ','600503.SH','000912.SZ','603029.SH','002637.SZ','002661.SZ','300268.SZ',
         '000952.SZ','600048.SH','300658.SZ','002133.SZ','300564.SZ','688500.SH','603079.SH','600875.SH','300136.SZ','002881.SZ',
         '600785.SH','300970.SZ','300228.SZ','600594.SH','603737.SH','600510.SH','002208.SZ','603887.SH','301167.SZ',
         '300086.SZ','000582.SZ','688117.SH','002253.SZ','000668.SZ','002961.SZ','603823.SH','600499.SH','300413.SZ','603999.SH']
inl = ','.join(f"'{c}'" for c in codes)
q = f"SELECT ts_code, trade_date, close, pct_chg FROM daily WHERE ts_code IN ({inl}) AND trade_date >= '20260910' ORDER BY ts_code, trade_date"
by = defaultdict(list)
for r in db.execute(q).fetchall():
    if r[0] == '000017.SZ': print('rawrow', r)
    by[r[0]].append((r[1], r[2], r[3] if len(r) > 3 else None))
for k, v in sorted(by.items()):
    v = [x if len(x) == 3 else (x[0], x[1], None) for x in v]
    cl = [x[1] for x in v]
    pc = [x[2] for x in v]
    last = cl[-1]
    c3 = (last/cl[-4]-1)*100 if len(cl) >= 4 else float('nan')
    hi = max(cl[-20:])
    dist = (last/hi-1)*100
    lim = [f"{v[i][0]}:{pc[i]:+.1f}" for i in range(len(v)) if pc[i] is not None and pc[i] > 9.0]
    print(f"{k} 0924收 {last} 3d {c3:+.1f}% vs20HI {dist:+.1f}% 涨停[{','.join(lim)}] 近3日pct {[round(pc[i],1) if pc[i] is not None else None for i in range(len(v)-3,len(v))]}")
