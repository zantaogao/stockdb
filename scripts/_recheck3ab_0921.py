# -*- coding: utf-8 -*-
"""复检A/B：ⓐ生存者偏差（库是否保留退市股历史） ⓑ20/50/30 vs 0/50/50 到底差在哪
（report里 0/50/50=0.421 t=1.33 正年12/18；20/50/30=0.331 t=1.30 正年12/18，非恒等，我OPS_FACTS写的'同分'存疑）"""
import duckdb, glob, os, sqlite3
import numpy as np, pandas as pd
HOME = os.path.expanduser('~')
con = duckdb.connect(f'{HOME}/.hermes/stockdb/tushare.db', read_only=True)
print('ⓐ 库保留退市股历史核查：最后交易日<20260901的票数 及 其最后一年分布')
dead = con.execute("SELECT ts_code, max(trade_date) mx FROM daily GROUP BY 1 HAVING max(trade_date) < '20260901'").df()
print(dead.mx.str[:4].value_counts().sort_index().to_string())
# 抽一个真退市票看它2014~退市期间的历史在不在
samp = dead[dead.mx < '20160101'].head(3)
for ts, mx in samp.values:
    cnt = con.execute(f"SELECT count(*), min(trade_date), max(trade_date) FROM daily WHERE ts_code='{ts}'").fetchone()
    print(f'   {ts}: 在库{cnt[0]}天 {cnt[1]}~{cnt[2]}')
con.close()

print('\nⓑ 20/50/30 vs 0/50/50 池差异定位')
d = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(f'{HOME}/.hermes/stockdb/analysis/cmmr_grid_days/*.csv'))], ignore_index=True)
d['date'] = d['date'].astype(int)
a = d[d.w=='20/50/30'].set_index('date'); b = d[d.w=='0/50/50'].set_index('date')
j = a.join(b, lsuffix='_a', rsuffix='_b').dropna(subset=['ex_a','ex_b'])
print(f'重叠日{len(j)} pool_n不同天数{int((j.pool_n_a!=j.pool_n_b).sum())} ex不同天数{int((j.ex_a!=j.ex_b).sum())}')
print(f'日均: 20/50/30={j.ex_a.mean()*100:+.3f}pp  0/50/50={j.ex_b.mean()*100:+.3f}pp')
# 只在pool_n相同但ex不同的日子，才真是选票不同
same_pool_diff_ex = j[(j.pool_n_a==j.pool_n_b)&(j.ex_a!=j.ex_b)]
print(f'池大小相同但选票不同的日数: {len(same_pool_diff_ex)}')
