"""真实 ex5/ex10/ex20 口径验证（2026-09-26）：
ex_n = 个股chg_n - 同期上证chg_n（与 feat_tushare.compute_features 23-25 位同式）。
在**旧死维样本**上现算（chg5=f0 等特征列是好的，只有 ex 列死了），
量化这三个单维近 12 月日均截面 RankIC——决定 v5 样本重建时 ex 维喂法。
"""
import duckdb, numpy as np, pandas as pd
from scipy import stats

BASE = '/Users/zantao/.hermes/stockdb'
tun = duckdb.connect()
smp = tun.execute(f"select date, f0, f1, f2, y10 from read_parquet('{BASE}/analysis/retrain_20260926/samples_10d.parquet') where date >= '20250901'").df()
tun.close()

con = duckdb.connect(f'{BASE}/tushare.db', read_only=True)
idx = con.execute("select date, close from index_daily where index_code='000001' and date >= '2025-06-01' order by date").df()
idict = {str(d).replace('-', ''): float(c) for d, c in zip(idx['date'], idx['close'])}
cal = sorted(idict); pos = {d: i for i, d in enumerate(cal)}

rows = []
for d in sorted(set(smp['date']) & set(cal)):
    i = pos[d]
    if i < 20: continue
    g = smp[smp['date'] == d]
    if len(g) < 500: continue
    rec = {'date': d}
    for lag, fcol, name in [(5, 'f0', 'chg5'), (10, 'f1', 'chg10'), (20, 'f2', 'chg20')]:
        idxr = idict[cal[i]] / idict[cal[i-lag]] - 1
        ex = g[fcol].to_numpy() / 100.0 - idxr
        rec['ic_' + name] = stats.spearmanr(ex, g['y10'].to_numpy())[0]
    rows.append(rec)
df = pd.DataFrame(rows)
cols = list(df.columns)
print(f"样本日数 n={len(df)}  窗口 {df[cols[0]].min()}~{df[cols[0]].max()}")
for name in ['chg5', 'chg10', 'chg20']:
    s = df['ic_' + name].dropna()
    t, p = stats.ttest_1samp(s, 0)
    print(f'  真实ex({name}) 日均截面RankIC: {s.mean():+.4f}  p={p:.3g}  正IC天 {100*(s>0).mean():.0f}%')
df.to_csv(f'{BASE}/analysis/feat_ic_audit_0926/real_ex_daily.csv', index=False)
con.close()
