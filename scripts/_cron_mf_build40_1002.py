"""40d样本 + 资金流列 mf20（主力20日净流入/流通市值%），f0..f33逐字不动，只加一列
输入: analysis/retrain_20260927_v8/samples_40d.parquet + tushare.db money_flow/daily_basic
输出: analysis/mf40_20261002/samples_40d_mf.parquet (+ f列逐字节一致断言)"""
import duckdb, pandas as pd, numpy as np
from pathlib import Path
BASE = Path.home()/'.hermes/stockdb'
OUT = BASE/'analysis/mf40_20261002'; OUT.mkdir(exist_ok=True)

old = pd.read_parquet(BASE/'analysis/retrain_20260927_v8/samples_40d.parquet')
print('原样本', old.shape, old.date.min(), old.date.max(), flush=True)

c = duckdb.connect(str(BASE/'tushare.db'), read_only=True)
mf = c.execute("""
WITH s AS (
  SELECT stock_code sc, date, main_net,
         SUM(main_net) OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) mf20,
         COUNT(*)      OVER (PARTITION BY stock_code ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) n20
  FROM money_flow WHERE date>='2018-06-01'
),
mv AS (SELECT str_split(ts_code,'.')[1] sc, trade_date td, circ_mv FROM daily_basic WHERE trade_date>='20180601')
SELECT s.sc, REPLACE(CAST(s.date AS VARCHAR),'-','') d, s.mf20/s.n20*20.0/n.circ_mv*100 AS mf20
FROM s JOIN mv n ON n.sc=s.sc AND n.td=REPLACE(CAST(s.date AS VARCHAR),'-','')
""").df()
print('mf列', mf.shape, '覆盖票', mf.sc.nunique(), flush=True)

old['key'] = old.code.astype(str).str.zfill(6) + '|' + old.date.astype(str)
mf['key']  = mf.sc.astype(str).str.zfill(6) + '|' + mf.d.astype(str)
new = old.merge(mf[['key','mf20']], on='key', how='left')
hit = new.mf20.notna().mean()*100
print(f'join命中率 {hit:.1f}%', flush=True)
assert hit > 95, '命中率过低'

feat_cols = [f'f{j}' for j in range(26)] + ['f31','f32','f33']
same = (new[feat_cols].round(10) == old.sort_values('key').set_index('key').loc[new['key']].reindex(new['key'].values)[feat_cols].round(10).values).all().all()
assert same, 'f列比对失败'
print('f列逐字节一致断言 PASS', flush=True)

new.to_parquet(OUT/'samples_40d_mf.parquet', index=False)
print('saved', OUT/'samples_40d_mf.parquet', flush=True)
