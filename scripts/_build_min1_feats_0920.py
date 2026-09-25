# -*- coding: utf-8 -*-
# 1分钟尾盘/隔夜特征构建（2026-09-20）：tdx_archive.db min1_archive 2026全年
# 输出 analysis/min1_feats_0920.parquet：code(6位) date(YYYY-MM-DD) + 10 维
# gap_ret/tail5_ret/tail30_ret/last_vol_share/vwap_dev/tail_vwap_dev/tail_up_ratio/vd_o30/vd_t30/vd_m2
# + ovr20 隔夜动量占比20（Σgap收益/Σ|日内收益|，仿 v4d f34 口径）
import duckdb, pandas as pd, numpy as np, os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = os.path.expanduser('~/.hermes/stockdb')

con = duckdb.connect(BASE + '/tdx_archive.db', read_only=True)
feat = con.execute("""
WITH m AS (
  SELECT CAST(date AS VARCHAR) AS date, code, tm, open, high, low, close, volume
  FROM min1_archive
  WHERE date >= 20260101 AND (code LIKE '0%' OR code LIKE '3%' OR code LIKE '6%')
),
b AS (
  SELECT *,
    volume*close AS amt,
    ROW_NUMBER() OVER (PARTITION BY date, code ORDER BY tm DESC) AS rev_rank,
    CASE WHEN tm BETWEEN 571 AND 600 THEN 'o30'
         WHEN tm BETWEEN 601 AND 689 THEN 'm1'
         WHEN tm BETWEEN 690 AND 839 THEN 'm2'
         WHEN tm BETWEEN 840 AND 870 THEN 'a30'
         WHEN tm BETWEEN 871 AND 900 THEN 't30' END AS bucket
  FROM m
)
SELECT date, code,
  COUNT(*) AS n_bars,
  FIRST(open ORDER BY tm) AS open_day,
  MAX(CASE WHEN tm=900 THEN close END) AS close_eod,
  MAX(CASE WHEN bucket='t30' AND tm=900 THEN close END)
    / MAX(CASE WHEN bucket='a30' THEN close END) - 1 AS tail30_ret,
  MAX(CASE WHEN tm=900 THEN close END)/NULLIF(MAX(CASE WHEN tm=895 THEN close END),0)-1 AS tail5_ret,
  MAX(CASE WHEN rev_rank=1 THEN volume END)/NULLIF(SUM(volume),0) AS last_vol_share,
  SUM(CASE WHEN bucket='o30' THEN volume ELSE 0 END)/NULLIF(SUM(volume),0) AS vd_o30,
  SUM(CASE WHEN bucket='t30' THEN volume ELSE 0 END)/NULLIF(SUM(volume),0) AS vd_t30,
  SUM(CASE WHEN bucket='m2'  THEN volume ELSE 0 END)/NULLIF(SUM(volume),0) AS vd_m2,
  SUM(CASE WHEN bucket='t30' THEN amt ELSE 0 END)/NULLIF(SUM(CASE WHEN bucket='t30' THEN volume ELSE 0 END),0)
    / NULLIF(SUM(amt)/NULLIF(SUM(volume),0),0) - 1 AS tail_vwap_dev,
  AVG(CASE WHEN bucket='t30' AND close>=open THEN 1.0 ELSE 0 END) AS tail_up_ratio,
  SUM(amt)/NULLIF(SUM(volume),0) AS vwap
FROM b
GROUP BY date, code
HAVING COUNT(*) >= 200
""").df()
con.close()
print('日频行数', len(feat), '天数', feat['date'].nunique(), flush=True)

feat['vwap_dev'] = feat['close_eod']/feat['vwap'] - 1
feat = feat.sort_values(['code','date'])
feat['close_prev'] = feat.groupby('code')['close_eod'].shift(1)
feat['gap_ret'] = feat['open_day']/feat['close_prev'] - 1
feat['day_ret'] = feat['close_eod']/feat['close_prev'] - 1
feat['intra_ret'] = feat['close_eod']/feat['open_day'] - 1
g = feat.groupby('code')
ov = (g['gap_ret'].transform(lambda s: s.rolling(20, min_periods=15).sum()))
ai = (g['intra_ret'].transform(lambda s: s.rolling(20, min_periods=15).apply(lambda x: np.abs(x).sum(), raw=True)))
feat['ovr20'] = ov / ai.replace(0, np.nan)

feat['code6'] = feat['code'].astype(str).str.zfill(6)
feat['date2'] = feat['date'].str[:4] + '-' + feat['date'].str[4:6] + '-' + feat['date'].str[6:8]
cols = ['code6','date2','gap_ret','tail30_ret','tail5_ret','last_vol_share','vwap_dev','tail_vwap_dev','tail_up_ratio','vd_o30','vd_t30','vd_m2','ovr20']
out = feat[cols].rename(columns={'code6':'code','date2':'date'}).drop_duplicates(['code','date'])
out.to_parquet(BASE + '/analysis/min1_feats_0920.parquet')
print('saved', len(out), out['date'].min(), out['date'].max(), flush=True)
print(out.describe().loc[['mean','std','min','max']].round(4).to_string(), flush=True)
