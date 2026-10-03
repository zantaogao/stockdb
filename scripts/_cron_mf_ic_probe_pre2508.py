"""资金流特征IC探针: main_net/retail_net 衍生特征 vs 未来10/20日收益 截面RankIC"""
import duckdb, pandas as pd, numpy as np
c = duckdb.connect('tushare.db', read_only=True)
# 近300个交易日窗口
df = c.execute("""
WITH mf AS (
  SELECT stock_code, date, main_net, retail_net, main_pct,
         SUM(main_net) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS mf5,
         SUM(main_net) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS mf20
  FROM money_flow WHERE date >= '2025-01-01' AND date < '2025-08-01'
),
px AS (
  SELECT REPLACE(ts_code,'.SH','') sc, ts_code, trade_date, close FROM daily WHERE trade_date>='20250101' AND trade_date<'20250901'
),
fwd AS (
  SELECT ts_code, trade_date,
         LEAD(close,10) OVER (PARTITION BY ts_code ORDER BY trade_date)/close-1 AS f10,
         LEAD(close,20) OVER (PARTITION BY ts_code ORDER BY trade_date)/close-1 AS f20
  FROM daily WHERE trade_date>='20250101' AND trade_date<'20250901'
),
mv AS (SELECT REPLACE(ts_code,'.SH','') sc, trade_date, circ_mv FROM daily_basic WHERE trade_date>='20250101' AND trade_date<'20250901')
SELECT m.stock_code, m.date, m.main_net, m.retail_net, m.main_pct, m.mf5, m.mf20,
       v.circ_mv, f.f10, f.f20,
       LAG(p.close,1) OVER (PARTITION BY p.ts_code ORDER BY p.trade_date) AS prev_close,
       p.close
FROM mf m
JOIN px p ON p.sc=m.stock_code AND REPLACE(CAST(m.date AS VARCHAR),'-','')=p.trade_date
LEFT JOIN mv v ON v.sc=p.sc AND v.trade_date=p.trade_date
JOIN fwd f ON f.ts_code=p.ts_code AND f.trade_date=p.trade_date
""").df()
df = df.dropna(subset=['circ_mv','f10'])
df['d1'] = (df.close/df.prev_close-1)
df['mf1_ratio'] = df.main_net/(df.circ_mv*1e4)*1e2
df['mf5_ratio'] = df.mf5/(df.circ_mv*1e4)*1e2
df['mf20_ratio']= df.mf20/(df.circ_mv*1e4)*1e2
def daily_ic(g,col,y):
    if len(g)<200 or g[col].isna().all() or g[y].isna().all(): return np.nan
    sub=g[[col,y]].dropna()
    if len(sub)<200: return np.nan
    return sub[col].corr(sub[y],method='spearman')
feats={'main_net当日':('mf1_ratio','f10'),'main_net10d累计':('mf1_ratio','f20'),
       'main_net5d累计':('mf5_ratio','f10'),'main_net20d累计':('mf20_ratio','f10'),
       'main_pct当日':('main_pct','f10'),'retail_net当日':('retail_net','f10'),
       '当日涨幅对照':('d1','f10')}
print(f"样本: {df.date.nunique()}日 x 均{len(df)/df.date.nunique():.0f}票")
for name,(col,y) in feats.items():
    ics = df.groupby('date').apply(lambda g: daily_ic(g,col,y), include_groups=False).dropna()
    if len(ics)==0: print(name,"无IC"); continue
    m=ics.mean(); t=m/(ics.std()/np.sqrt(len(ics)))
    print(f"{name:14s} 日均RankIC={m:+.4f} NW-t≈{t:+.2f} 为正占比{(ics>0).mean()*100:.0f}% n={len(ics)}")
