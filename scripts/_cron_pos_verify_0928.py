# 步骤2.5 持仓日线核验（最近交易日 20260925 收盘口径）
import duckdb, json

codes = ['603202.SH','002454.SZ','605598.SH','688093.SH','300658.SZ','688186.SH','301093.SZ',
         '001332.SZ','603966.SH','301237.SZ','601615.SH','301283.SZ','600076.SH','301590.SZ',
         '603811.SH','301575.SZ','300651.SZ','301110.SZ']
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
q = """
SELECT ts_code, trade_date, close, pre_close, pct_chg FROM daily
WHERE ts_code IN ({}) AND trade_date <= '20260925'
ORDER BY ts_code, trade_date
""".format(','.join(f"'{c}'" for c in codes))
rows = con.execute(q).fetchall()
from collections import defaultdict
by = defaultdict(list)
for r in rows: by[r[0]].append(r)

# 榜内票一并拉
rank_codes = ['001225.SZ','002961.SZ','603823.SH','600499.SH','300086.SZ','000582.SZ','688117.SH',
              '002253.SZ','003040.SZ','000668.SZ','600785.SH','300970.SZ','300228.SZ','688500.SH',
              '600594.SH','603737.SH','600510.SH','002208.SZ','603887.SH','301167.SZ',
              '000952.SZ','600048.SH','002133.SZ','300564.SZ','603079.SH','600875.SH','300136.SZ','002881.SZ',
              '300413.SZ','603999.SH']
q2 = """
SELECT ts_code, trade_date, close FROM daily
WHERE ts_code IN ({}) AND trade_date <= '20260925'
ORDER BY ts_code, trade_date
""".format(','.join(f"'{c}'" for c in rank_codes))
for r in con.execute(q2).fetchall(): by[r[0]].append((r[0], r[1], r[2], None, None))

for c, rr in sorted(by.items()):
    rr = sorted(set(rr), key=lambda x: x[1])
    closes = [x[2] for x in rr]
    dates = [x[1] for x in rr]
    if len(closes) < 6:
        print(c, 'insufficient', len(closes)); continue
    last = closes[-1]
    c5 = (last/closes[-6]-1)*100          # 5日涨幅
    c10 = (last/closes[-11]-1)*100 if len(closes)>=11 else float('nan')
    hi20 = max(closes[-20:]) if len(closes)>=20 else max(closes)
    dist_hi = (last/hi20-1)*100           # 距20日高点
    # 连涨天数
    up = 0
    for i in range(len(rr)-1, 0, -1):
        p = (rr[i][2]/rr[i-1][2]-1)*100
        if p > 0: up += 1
        else: break
    # 近3日累计
    a3 = (last/closes[-4]-1)*100
    print(f"{c} last {last:.2f} @{dates[-1]} | 5d {c5:+.1f}% | 10d {c10:+.1f}% | 3d {a3:+.1f}% | vs20dHigh {dist_hi:+.1f}% | 连涨{up}日")
