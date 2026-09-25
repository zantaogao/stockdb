#!/usr/bin/env python3
"""分钟线信号挖掘 v1 (2026-09-02)
从 tdx_archive.db min1_archive 聚合 11 个日内微观特征，
对 signal_history(final_score/old_score/cmmr) + fusion_3f_score 算滚动 Rank IC。
输出: ~/.hermes/stockdb/analysis/min1_features_0902.parquet + IC 表打印
"""
import duckdb, pandas as pd, numpy as np

ARCH = '/Users/zantao/.hermes/stockdb/tdx_archive.db'
SIG  = '/Users/zantao/.hermes/stockdb/signals.db'
OUT  = '/Users/zantao/.hermes/stockdb/analysis/min1_features_0902.parquet'

con = duckdb.connect(ARCH, read_only=True)
# 只保留A股个股（00/30/60/68开头），排除指数
feat = con.execute("""
WITH m AS (
  SELECT CAST(date AS VARCHAR) AS date, code, tm, open, high, low, close, volume
  FROM min1_archive
  WHERE code LIKE '0%' OR code LIKE '3%' OR code LIKE '6%'
),
b AS (
  SELECT *,
    volume*close AS amt,
    (high-low)/NULLIF((high+low)/2,0) AS bar_amp,
    CASE WHEN tm BETWEEN 571 AND 600 THEN 'o30'
         WHEN tm BETWEEN 601 AND 689 THEN 'm1'
         WHEN tm BETWEEN 690 AND 839 THEN 'm2'
         WHEN tm BETWEEN 840 AND 870 THEN 'a30'
         WHEN tm BETWEEN 871 AND 900 THEN 't30' END AS bucket,
    -- 尾盘笔序号：当日倒数第1..N笔
    ROW_NUMBER() OVER (PARTITION BY date,code ORDER BY tm DESC) AS rev_rank
  FROM m
)
SELECT date, code,
  COUNT(*) AS n_bars,
  MAX(CASE WHEN tm=571 THEN close END) / MIN(CASE WHEN tm=571 THEN open END) - 1 AS open30_ret,
  MAX(CASE WHEN rev_rank=1 THEN close END) / MAX(CASE WHEN bucket='a30' AND rev_rank=181 THEN NULL ELSE close END) - 1 AS _dummy,
  -- tail30: 14:31收盘 / 14:30前最后收盘(=bucket a30 最大tm的close)
  MAX(CASE WHEN bucket='t30' AND tm=900 THEN close END)
    / MAX(CASE WHEN bucket='a30' THEN close END) - 1 AS tail30_ret,
  SUM(amt)/NULLIF(SUM(volume),0) AS vwap,
  MAX(CASE WHEN tm=900 THEN close END) AS close_eod,
  FIRST(open ORDER BY tm) AS open_day,
  LAST(close ORDER BY tm) AS close_prev,   -- 占位，次日处理
  VARIANCE(LN(close/NULLIF(open,0))) AS rv_1m,
  AVG(bar_amp) AS amp_intra,
  SUM(CASE WHEN bucket='o30' THEN volume ELSE 0 END)/NULLIF(SUM(volume),0) AS vd_o30,
  SUM(CASE WHEN bucket='t30' THEN volume ELSE 0 END)/NULLIF(SUM(volume),0) AS vd_t30,
  SUM(CASE WHEN bucket='m1' THEN volume ELSE 0 END)/NULLIF(SUM(volume),0) AS vd_m1,
  SUM(CASE WHEN bucket='m2' THEN volume ELSE 0 END)/NULLIF(SUM(volume),0) AS vd_m2,
  -- 尾盘急拉: 最后5分钟涨幅
  MAX(CASE WHEN tm=900 THEN close END)/NULLIF(MAX(CASE WHEN tm=895 THEN close END),0)-1 AS tail5_ret,
  -- 尾盘30分钟收益的连续性: 尾盘上涨分钟占比
  AVG(CASE WHEN bucket='t30' AND close>=open THEN 1.0 ELSE 0 END) AS tail_up_ratio,
  -- 尾盘量占比的极端: 最后一笔量占全日
  MAX(CASE WHEN rev_rank=1 THEN volume END)/NULLIF(SUM(volume),0) AS last_vol_share,
  -- 尾盘30min VWAP 相对全日 vwap
  SUM(CASE WHEN bucket='t30' THEN amt ELSE 0 END)/NULLIF(SUM(CASE WHEN bucket='t30' THEN volume ELSE 0 END),0)
    / NULLIF(SUM(amt)/NULLIF(SUM(volume),0),0) - 1 AS tail_vwap_dev,
  -- 收盘价相对全日vwap偏离
  MAX(CASE WHEN tm=900 THEN close END)/NULLIF(SUM(amt)/NULLIF(SUM(volume),0),0)-1 AS close_vwap_dev
FROM b
GROUP BY date, code
HAVING COUNT(*) >= 200
""").df()
con.close()

# vwap/close 派生
feat['vwap_dev'] = feat['close_eod']/feat['vwap'] - 1
feat['gap_ret']  = feat['open_day']/feat['close_prev'] - 1  # 稍后用前日close修
feat = feat.drop(columns=['_dummy'])

# 前日 close 用于 gap：用当日最后一笔=当日close，自关联前一日
feat['date_i'] = pd.to_datetime(feat['date'], format='%Y%m%d')
feat = feat.sort_values(['code','date_i'])
feat['close_prev'] = feat.groupby('code')['close_eod'].shift(1)
feat['gap_ret'] = feat['open_day']/feat['close_prev'] - 1
feat['day_ret'] = feat['close_eod']/feat['close_prev'] - 1

feat.to_parquet(OUT)
print('features:', len(feat), 'days:', feat['date'].nunique(), feat['date'].min(), feat['date'].max())

# 信号 + 未来收益
sc = duckdb.connect(SIG, read_only=True)
sig = sc.execute("""
SELECT date, stock_code AS code,
  final_score, old_score, cmmr_score, fusion_score_cmmr, reg10_pred, reg20, reg40
FROM signal_history
""").df()
sig['date'] = sig['date'].astype(str).str.replace('-','',regex=False)
sig = sig.drop_duplicates(subset=['date','code'], keep='last')
f3 = sc.execute("""
SELECT date, stock_code AS code, fusion_3f_score, signal
FROM fusion_3f_signals
""").df()
f3['date'] = f3['date'].astype(str).str.replace('-','',regex=False)
sc.close()

daily = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True).execute("""
SELECT REPLACE(trade_date,'-','') AS date, ts_code AS code, close
FROM daily WHERE trade_date >= '20260501'
""").df()
daily['code'] = daily['code'].str[:6]

d = daily.sort_values(['code','date']).copy()
d['date_i'] = pd.to_datetime(d['date'], format='%Y%m%d')
for h in (1,3,5,10):
    d[f'fwd{h}'] = d.groupby('code')['close'].shift(-h)/d['close'] - 1

base = feat.merge(d, on=['date','code'], how='inner')
base = base.merge(sig, on=['date','code'], how='left')
base = base.merge(f3, on=['date','code'], how='left')
base = base[base['date'] >= '20260803']  # 首批失真期后
print('joined:', len(base))

feats = ['open30_ret','tail30_ret','tail5_ret','tail_up_ratio','vwap_dev','close_vwap_dev',
         'rv_1m','amp_intra','gap_ret','vd_o30','vd_t30','vd_m1','vd_m2','last_vol_share','tail_vwap_dev',
         'day_ret']
targets = [c for c in ['fwd1','fwd3','fwd5','fwd10'] ]
sigcols = [c for c in ['final_score','old_score','cmmr_score','fusion_score_cmmr','reg10_pred',
                       'reg20','reg40','fusion_3f_score'] if c in base.columns]

rows=[]
for f in feats:
    for t in targets:
        sub = base[[f,t]].dropna()
        ic = sub[f].corr(sub[t], method='spearman')
        rows.append({'feat':f,'target':t,'ic':round(ic,4),'n':len(sub)})
# 信号列对照（同一样本子集，证明特征是否超越现有信号）
for s in sigcols:
    for t in ['fwd5']:
        sub = base[[s,t]].dropna()
        ic = sub[s].corr(sub[t], method='spearman')
        rows.append({'feat':'SIG:'+s,'target':t,'ic':round(ic,4),'n':len(sub)})
res = pd.DataFrame(rows)
pd.set_option('display.width', 200)
print("=== 全样本 Rank IC (8/3起) ===")
print(res.pivot(index='feat', columns='target', values='ic').to_string())
res.to_csv('/Users/zantao/.hermes/stockdb/analysis/min1_ic_0902.csv', index=False)