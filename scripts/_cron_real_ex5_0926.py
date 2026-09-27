"""真实 ex5 口径验证（2026-09-26）：ex5 = 个股chg5 - 同期上证chg5，近12月日均截面 RankIC。
决定样本重建时 ex 维符号/喂法（feat_tushare 公式 chg5 - idxchg 的符号是否正确）。
"""
import duckdb, numpy as np, pandas as pd
from scipy import stats

BASE = '/Users/zantao/.hermes/stockdb'
tun = duckdb.connect()
smp = tun.execute(f"select date, f0, y10 from read_parquet('{BASE}/analysis/retrain_20260926/samples_10d.parquet') where date >= '20250901'").df()
tun.close()

con = duckdb.connect(f'{BASE}/tushare.db', read_only=True)
idx = con.execute("select date, close from index_daily where index_code='000001.SH' and date >= '2025-06-01' order by date").df()
idict = {str(d).replace('-', ''): float(c) for d, c in zip(idx['date'], idx['close'])}
cal = sorted(idict); pos = {d: i for i, d in enumerate(cal)}

rows = []
for d in sorted(set(smp['date']) & set(cal)):
    i = pos[d]
    if i < 20: continue
    g = smp[smp['date'] == d]
    if len(g) < 500: continue
    idx5 = idict[cal[i]] / idict[cal[i-5]] - 1
    ex5 = g['f0'].to_numpy() / 100.0 - idx5  # f0=chg5 百分数
    rows.append({'date': d, 'ic': stats.spearmanr(ex5, g['y10'])[0]})
df = pd.DataFrame(rows)
t, p = stats.ttest_1samp(df['ic'], 0)
print('真实ex5(=chg5-同期上证chg5) 近12月日均截面RankIC: %+.4f  p=%.4g  n=%d  正IC天 %.0f%%' % (
    df['ic'].mean(), p, len(df), 100 * (df['ic'] > 0).mean()))
df.to_csv(f'{BASE}/analysis/feat_ic_audit_0926/real_ex5_daily.csv', index=False)
con.close()
