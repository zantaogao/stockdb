import duckdb
codes = ['001332.SZ','002674.SZ','603966.SH','301237.SZ','688399.SH','300952.SZ','300818.SZ','301093.SZ','605598.SH','688486.SH',
'605286.SH','300935.SZ','603089.SH','603036.SH','603758.SH','300779.SZ','002686.SZ','002244.SZ','002742.SZ','600066.SH',
'688217.SH','300886.SZ','603801.SH','603382.SH','688793.SH','001277.SZ','301166.SZ','300937.SZ','688004.SH','301130.SZ',
'600609.SH','000897.SZ','600731.SH','003017.SZ','000421.SZ','300321.SZ','601886.SH','600512.SH','688099.SH','600563.SH',
'688275.SH','688063.SH','688191.SH','603863.SH','002595.SZ','688155.SH','300905.SZ','688355.SH']
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
inlist = ','.join(f"'{c}'" for c in codes)
q = f"""
WITH d AS (
  SELECT ts_code, trade_date, close, pct_chg, high, low,
         ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn
  FROM daily WHERE trade_date >= '20260801' AND ts_code IN ({inlist})
)
SELECT ts_code,
  MAX(CASE WHEN rn=1 THEN close END) as c1,
  MAX(CASE WHEN rn=6 THEN close END) as c6,
  AVG(CASE WHEN rn<=20 THEN close END) as ma20,
  STDDEV_SAMP(CASE WHEN rn<=20 THEN close END) as sd20,
  MAX(CASE WHEN rn<=20 THEN close END) as hi20,
  MAX(CASE WHEN rn<=20 THEN high END) as h20,
  MIN(CASE WHEN rn<=20 THEN low END) as l20
FROM d WHERE rn<=20 GROUP BY ts_code ORDER BY ts_code
"""
for r in con.execute(q).fetchall():
    ts,c1,c6,ma20,sd,hi20,h20,l20 = r
    if c1 is None or ma20 is None: print(ts,'insufficient'); continue
    bias20 = (c1/ma20-1)*100
    rng = h20-l20
    bollpos = (c1-(ma20-2*sd))/rng*100 if rng>0 else -1
    up = ma20+2*sd
    ret5 = (c1/c6-1)*100 if c6 else None
    newhi = 'Y' if c1>=hi20*0.999 else 'N'
    print(f"{ts} close={c1:.2f} bias20={bias20:+.1f}% bollpos={bollpos:.0f}% upper={up:.2f} ret5={ret5:+.1f}% 20dnewhi={newhi}")