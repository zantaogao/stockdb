"""v5 重建样本 ex 维有效性验证（2026-09-26）：
样本里 f23/f24/f25 = ex5/ex10/ex20。逐日截面 RankIC（对 y10/y20/y40），
证明修复后的 ex 维是否为真信号（旧样本恒 0 兜底 → 死维）。
"""
import duckdb, numpy as np, pandas as pd
from scipy import stats

BASE = '/Users/zantao/.hermes/stockdb/analysis/retrain_20260926'
tun = duckdb.connect()

for t, ycol in [('10d', 'y10'), ('20d', 'y20'), ('40d', 'y40')]:
    df = tun.execute(f"select date, f23, f24, f25, {ycol} from read_parquet('{BASE}/samples_{t}.parquet')").df()
    rows = []
    for d, g in df.groupby('date'):
        if len(g) < 500: continue
        rec = {'date': d}
        for fi, fn in [(23, 'ex5'), (24, 'ex10'), (25, 'ex20')]:
            v = g[f'f{fi}'].to_numpy()
            rec['ic_' + fn] = stats.spearmanr(v, g[ycol].to_numpy())[0] if np.isfinite(v).sum() > 100 and v.std() > 1e-12 else np.nan
        rows.append(rec)
    out = pd.DataFrame(rows)
    print(f'=== {t} n_days={len(out)} ===')
    for fn in ['ex5', 'ex10', 'ex20']:
        s = out['ic_' + fn].dropna()
        if len(s) > 30:
            tstat, p = stats.ttest_1samp(s, 0)
            print(f'  {fn}: 日均IC={s.mean():+.4f}  p={p:.4g}  n={len(s)}  正IC天={100*(s>0).mean():.0f}%')
        else:
            print(f'  {fn}: 有效天数不足({len(s)})')
    out.to_csv(f'/Users/zantao/.hermes/stockdb/analysis/feat_ic_audit_0926/v5fix_ex_{t}_daily.csv', index=False)
tun.close()
