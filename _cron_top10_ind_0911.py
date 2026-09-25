import duckdb
t = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
lists = {
 '三模型融合': ['603090.SH','001332.SZ','688377.SH','603966.SH','688155.SH','688636.SH','301283.SZ','600363.SH','300724.SZ','300812.SZ'],
 '10d独立': ['600076.SH','300328.SZ','603090.SH','688210.SH','300357.SZ','600785.SH','002491.SZ','000802.SZ','603226.SH','688775.SH'],
 '中枢版': ['000065.SZ','300050.SZ','300551.SZ','002628.SZ','002410.SZ','600246.SH','300784.SZ','002941.SZ','605222.SH','001231.SZ'],
 '中枢+三模型': ['300274.SZ','688576.SH','603307.SH','301548.SZ','300668.SZ','002335.SZ','688059.SH','603059.SH','300680.SZ','002956.SZ'],
}
codes = sorted({c for v in lists.values() for c in v})
inlist = ','.join(f"'{c}'" for c in codes)
rows = t.execute(f"""
WITH d AS (
  SELECT ts_code, trade_date, close, pct_chg, vol, amount,
         ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn
  FROM daily WHERE ts_code IN ({inlist}) AND trade_date <= '20260911'
)
SELECT ts_code, trade_date, close, pct_chg, vol FROM d WHERE rn<=61 ORDER BY ts_code, trade_date
""").fetchall()
from collections import defaultdict
series = defaultdict(list)
for r in rows: series[r[0]].append((r[1], r[2], r[3], r[4]))
import statistics
for name, lst in lists.items():
    print('=====', name)
    for c in lst:
        s = series.get(c)
        if not s or len(s) < 21:
            print(c, 'INSUFFICIENT', len(s) if s else 0); continue
        closes = [x[1] for x in s]  # ascending? ordered trade_date asc within rn<=61 -> rn61 oldest first
        # rn<=61 ordered by trade_date asc
        close = closes[-1]
        ma20 = sum(closes[-20:])/20
        dev = (close/ma20-1)*100
        # boll
        last20 = closes[-20:]
        sd = statistics.pstdev(last20)
        up, lo = ma20+2*sd, ma20-2*sd
        bollpos = (close-lo)/(up-lo)*100 if up>lo else 50
        ret5 = (close/closes[-6]-1)*100 if len(closes)>=6 else None
        hi20 = max(closes[-20:])
        dist_hi20 = (close/hi20-1)*100
        # 5d before: ret5 uses closes[-6]
        vols = [x[3] for x in s]
        volratio = vols[-1]/(sum(vols[-6:-1])/5) if sum(vols[-6:-1])>0 else None
        last5pct = [x[2] for x in s[-5:]]
        print(f"{c} close={close:.2f} devMA20={dev:+.1f}% boll={bollpos:.0f}% ret5={ret5:+.1f}% distHi20={dist_hi20:+.1f}% volX={volratio:.2f} pct5={last5pct}")
